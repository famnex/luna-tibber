"""Self-update via a separate user service. Stdlib-only; never runs inverter commands."""
import argparse
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import time
from urllib.request import urlopen
import uuid

REMOTE_URLS={'https://github.com/famnex/luna-tibber.git','https://github.com/famnex/luna-tibber',
             'git@github.com:famnex/luna-tibber.git','ssh://git@github.com/famnex/luna-tibber.git'}
ACTIVE={'queued','checking','dependencies','testing','installing','restarting','rollback'}
SERVICE='luna-web.service'


class UpdateError(Exception):pass


def read_status(folder):
    try:data=json.loads((folder/'update-state.json').read_text())
    except (OSError,ValueError):return {'state':'idle','message':'Bereit für Updates'}
    if not isinstance(data,dict):return {'state':'idle','message':'Bereit für Updates'}
    if data.get('state') in ACTIVE and time.time()-data.get('at',0)>30:
        try:
            cmd=Path(f"/proc/{data['pid']}/cmdline").read_bytes()
            if data.get('token','').encode() not in cmd:raise OSError()
        except (OSError,KeyError):
            data.update(state='failed',message='Update-Prozess beendet. Details in update.log prüfen.')
    return data


def busy(folder):return read_status(folder).get('state') in ACTIVE


def write_status(folder,state,message,**data):
    try:previous=json.loads((folder/'update-state.json').read_text())
    except (OSError,ValueError):previous={}
    now=time.time()
    history=previous.get('steps',[]) if previous.get('token')==data.get('token') else []
    if previous.get('state')!=state or previous.get('message')!=message:
        history=[*history,{'state':state,'message':message,'at':now}][-16:]
    data.update(state=state,message=message,at=now,pid=os.getpid(),steps=history)

    path=folder/'update-state.json';tmp=path.with_suffix('.tmp')
    fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def run(args,cwd,timeout=60,log=None):
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_SSH_COMMAND':'ssh -oBatchMode=yes','PIP_DISABLE_PIP_VERSION_CHECK':'1'}
    try:
        result=subprocess.run([str(a) for a in args],cwd=cwd,env=env,stdout=subprocess.PIPE if log is None else log,
                              stderr=subprocess.PIPE if log is None else subprocess.STDOUT,text=True,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise UpdateError('Befehl nicht verfügbar oder Zeitlimit überschritten: '+Path(str(args[0])).name) from exc
    if result.returncode:
        raise UpdateError('Schritt fehlgeschlagen: '+Path(str(args[0])).name+'; Details gegebenenfalls in update.log')
    return (result.stdout or '').strip()


def git(folder,*args,**kwargs):return run(['git','-c','core.hooksPath=/dev/null',*args],folder,**kwargs)


def revision(folder):
    try:return git(folder,'rev-parse','HEAD',timeout=5)
    except UpdateError:return None


def inspect_repo(folder):
    if Path(git(folder,'rev-parse','--show-toplevel')).resolve()!=folder.resolve():raise UpdateError('Kein eigenständiger LUNA-Git-Klon')
    if git(folder,'remote','get-url','origin') not in REMOTE_URLS:raise UpdateError('Origin muss auf famnex/luna-tibber zeigen')
    if git(folder,'branch','--show-current')!='main':raise UpdateError('Automatische Updates benötigen den Branch main')
    if git(folder,'status','--porcelain','--untracked-files=normal'):raise UpdateError('Lokale Änderungen vorhanden; Update überschreibt sie nicht')
    return git(folder,'rev-parse','HEAD')


def start(folder,port=8099,tls=False,old_pid=None):
    if busy(folder):raise ValueError('Ein Update läuft bereits')
    if any(c in str(folder) for c in ('$', '%', '\n')):raise ValueError('Installationspfad für Systemdienst ungeeignet')
    try:
        inspect_repo(folder)
        run(['systemctl','--user','is-active','--quiet',SERVICE],folder,timeout=5)
    except UpdateError as exc:raise ValueError(str(exc)) from None
    token=uuid.uuid4().hex;area=folder/'.updates';area.mkdir(mode=0o700,exist_ok=True)
    runner=area/f'runner-{token}.py';shutil.copyfile(Path(__file__),runner);os.chmod(runner,0o600)
    write_status(folder,'queued','Update wird gestartet',token=token)
    command=['systemd-run','--user',f'--unit=luna-update-{token}','--collect','--property=Type=exec','--property=UMask=0077',
             sys.executable,str(runner),'--apply',str(folder),'--token',token,'--port',str(port),'--old-pid',str(old_pid or os.getpid())]
    if tls:command.append('--tls')
    try:run(command,folder,timeout=15)
    except UpdateError as exc:
        write_status(folder,'failed','Update-Dienst konnte nicht gestartet werden',token=token)
        raise ValueError('Update benötigt einen erreichbaren systemd-Benutzerdienst') from exc


def requirements(folder):
    return {name:(folder/name).read_bytes() if (folder/name).exists() else b'' for name in ('requirements.txt','requirements-push.txt')}


def prepare_python(folder,stage,token,log):
    current=folder/'.venv/bin/python'
    if not current.exists():raise UpdateError('Die lokale .venv fehlt')
    push=run([current,'-c',"import importlib.util; print(int(importlib.util.find_spec('pywebpush') is not None))"],folder)=='1'
    before,after=requirements(folder),requirements(stage)
    changed=before['requirements.txt']!=after['requirements.txt'] or (push and before['requirements-push.txt']!=after['requirements-push.txt'])
    if not changed:
        run([current,'-m','pip','check'],folder,log=log)
        return current,None
    # Keep the new venv at this stable path: pip entry-point shebangs must remain valid.
    venv=folder/'.updates'/f'venv-{token}'
    run([sys.executable,'-m','venv',venv],folder,timeout=120,log=log)
    python=venv/'bin/python'
    run([python,'-m','pip','install','--timeout','20','--retries','2','-r',stage/'requirements.txt'],folder,timeout=1800,log=log)
    if push and after['requirements-push.txt']:
        run([python,'-m','pip','install','--timeout','20','--retries','2','-r',stage/'requirements-push.txt'],folder,timeout=1800,log=log)
    run([python,'-m','pip','check'],folder,log=log)
    return python,venv


def validate_stage(stage,python,log):
    run([python,'-m','compileall','-q',stage],stage,timeout=120,log=log)
    run([python,'-m','unittest','discover','-s',stage,'-q'],stage,timeout=300,log=log)
    if shutil.which('node'):
        for path in stage.glob('*.js'):run(['node','--check',path],stage,timeout=30,log=log)


def switch_venv(folder,venv,token):
    if venv is None:return None
    old=folder/'.venv';backup=folder/'.updates'/f'previous-venv-{token}'
    old.rename(backup)
    try:old.symlink_to(venv,target_is_directory=True)
    except Exception:backup.rename(old);raise
    return backup


def restore_venv(folder,backup):
    if backup is not None:
        link=folder/'.venv'
        if not link.is_symlink():raise UpdateError('Unerwartete Änderung der Python-Umgebung; automatische Wiederherstellung abgebrochen')
        link.unlink();backup.rename(link)


def wait_ready(folder,sha,port,tls,old_pid,timeout=60):
    context=ssl._create_unverified_context() if tls else None # Only the fixed loopback health endpoint; no credentials.
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            with urlopen(f"{'https' if tls else 'http'}://127.0.0.1:{port}/healthz",timeout=2,context=context) as response:data=json.load(response)
            if data.get('ok') and data.get('revision')==sha and data.get('pid')!=old_pid:return
        except (OSError,ValueError):pass
        time.sleep(1)
    raise UpdateError('Neustart hat keinen gesunden Webdienst bestätigt')


def apply(folder,token,port,tls,old_pid):
    folder=folder.resolve();area=folder/'.updates';area.mkdir(mode=0o700,exist_ok=True)
    original=target=None;stopped=False;backup=None;new_venv=None;stage=None
    logfd=os.open(folder/'update.log',os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
    with os.fdopen(logfd,'w') as log, (area/'update.lock').open('a') as lock, (folder/'controller.lock').open('a') as controller:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            fcntl.flock(controller,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            write_status(folder,'failed','Ein Controller oder Update läuft bereits',token=token);return
        def progress(state,message):write_status(folder,state,message,token=token,previous=original,target=target)
        try:
            progress('checking','Git-Stand und Voraussetzungen prüfen')
            original=inspect_repo(folder)
            # Never deploy while an unresolved hardware command exists.
            if any((folder/name).exists() for name in ('pending-charge.json','discharge-restore.json')):
                raise UpdateError('Ladeauftrag oder Entladefreigabe noch unbestätigt')
            request=folder/'discharge-request.json'
            if request.exists():
                until=json.loads(request.read_text()).get('until')
                if until and datetime.fromisoformat(until)>datetime.now(timezone.utc):
                    raise UpdateError('Manuelle Entladesperre zuerst aufheben')
            git(folder,'fetch','--no-tags','origin','main',timeout=120,log=log)
            target=git(folder,'rev-parse','refs/remotes/origin/main')
            if not re.fullmatch('[0-9a-f]{40}',target):raise UpdateError('Ungültiger Git-Zielstand')
            git(folder,'merge-base','--is-ancestor',original,target)
            if original==target:
                progress('current','Bereits auf dem neuesten Stand');return
            stage=area/f'source-{token}'
            git(folder,'worktree','add','--detach',str(stage),target,log=log)
            progress('dependencies','Abhängigkeiten prüfen und bei Bedarf vorbereiten')
            python,new_venv=prepare_python(folder,stage,token,log)
            progress('testing','Neue Version prüfen')
            validate_stage(stage,python,log)
            if inspect_repo(folder)!=original:raise UpdateError('Git-Stand wurde zwischenzeitlich geändert')
            progress('installing','Geprüftes Update übernehmen')
            stopped=True
            run(['systemctl','--user','stop',SERVICE],folder,timeout=90,log=log)
            git(folder,'merge','--ff-only','--no-edit',target,timeout=60,log=log)
            backup=switch_venv(folder,new_venv,token)
            progress('restarting','Webdienst neu starten')
            run(['systemctl','--user','start',SERVICE],folder,timeout=60,log=log)
            wait_ready(folder,target,port,tls,old_pid)
            git(folder,'worktree','remove','--force',str(stage),log=log);stage=None
            fcntl.flock(controller,fcntl.LOCK_UN)
            progress('done','Update erfolgreich · Webdienst bereit')
        except Exception as exc:
            message=str(exc) if isinstance(exc,UpdateError) else 'Unerwarteter Updatefehler; update.log prüfen'
            log.write(message+'\n');log.flush()
            if stopped:
                progress('rollback','Vorherige Version wiederherstellen')
                try:
                    run(['systemctl','--user','stop',SERVICE],folder,timeout=90,log=log)
                    # Revert only our clean checkout, never discard concurrent user edits.
                    if git(folder,'status','--porcelain','--untracked-files=no'):
                        raise UpdateError('Lokale Änderungen verhindern automatische Rückkehr')
                    git(folder,'reset','--hard',original,log=log)
                    restore_venv(folder,backup)
                    run(['systemctl','--user','start',SERVICE],folder,timeout=60,log=log)
                    wait_ready(folder,original,port,tls,old_pid)
                    message+=' · Vorherige Version wiederhergestellt'
                except Exception:
                    message+=' · Wiederherstellung nicht bestätigt; Dienst und update.log lokal prüfen'
            progress('failed',message)
        finally:
            if stage is not None:
                try:git(folder,'worktree','remove','--force',str(stage),log=log)
                except UpdateError:pass


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',type=Path,required=True)
    parser.add_argument('--token',required=True)
    parser.add_argument('--port',type=int,default=8099)
    parser.add_argument('--tls',action='store_true')
    parser.add_argument('--old-pid',type=int,required=True)
    args=parser.parse_args()
    if not re.fullmatch('[0-9a-f]{32}',args.token) or not 1<=args.port<=65535:raise SystemExit('Ungültige Updateparameter')
    os.umask(0o077)
    apply(args.apply,args.token,args.port,args.tls,args.old_pid)


if __name__=='__main__':main()

import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import updater

class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.remote=self.root/'remote.git';self.seed=self.root/'seed';self.app=self.root/'app'
        self.command('git','init','--bare','--initial-branch=main',str(self.remote))
        self.command('git','init','-b','main',str(self.seed))
        self.command('git','config','user.email','test@example.org',cwd=self.seed)
        self.command('git','config','user.name','Test',cwd=self.seed)
        (self.seed/'.gitignore').write_text('.updates/\n.venv/\ncontroller.lock\nupdate-state.json\nupdate-state.tmp\nupdate.log\n__pycache__/\nconfig.json\n')
        (self.seed/'main.py').write_text('VALUE=1\n')
        (self.seed/'test_main.py').write_text('import unittest\nfrom main import VALUE\nclass Smoke(unittest.TestCase):\n def test_value(self):self.assertGreater(VALUE,0)\n')
        (self.seed/'requirements.txt').write_text('')
        self.command('git','add','.',cwd=self.seed);self.command('git','commit','-m','Initial',cwd=self.seed)
        self.command('git','remote','add','origin',str(self.remote),cwd=self.seed)
        self.command('git','push','origin','main',cwd=self.seed)
        self.command('git','clone',str(self.remote),str(self.app))
        self.old=updater.revision(self.app);self.services=[]
        self.remote_patch=patch.object(updater,'REMOTE_URLS',{str(self.remote)});self.remote_patch.start()
    def tearDown(self):self.remote_patch.stop();self.tmp.cleanup()
    def command(self,*args,cwd=None):
        return subprocess.run(args,cwd=cwd,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
    def update_remote(self,code='VALUE=2\n'):
        (self.seed/'main.py').write_text(code)
        self.command('git','add','.',cwd=self.seed);self.command('git','commit','-m','Update',cwd=self.seed)
        self.command('git','push','origin','main',cwd=self.seed)
        return updater.revision(self.seed)
    def apply(self,health=None):
        original=updater.run
        def run(args,cwd,**kw):
            if args[0]=='systemctl':self.services.append(args[2]);return ''
            return original(args,cwd,**kw)
        with patch.object(updater,'run',side_effect=run),patch.object(updater,'prepare_python',return_value=(Path(sys.executable),None)),patch.object(updater,'wait_ready',side_effect=health):
            updater.apply(self.app,'a'*32,8099,False,123)
        return updater.read_status(self.app)
    def test_fast_forward_and_preserved_configuration(self):
        new=self.update_remote();(self.app/'config.json').write_text('local configuration')
        status=self.apply()
        self.assertEqual(status['state'],'done');self.assertEqual(updater.revision(self.app),new)
        self.assertEqual((self.app/'config.json').read_text(),'local configuration')
        self.assertEqual(self.services,['stop','start'])
    def test_current_does_not_restart(self):
        self.assertEqual(self.apply()['state'],'current');self.assertEqual(self.services,[])
    def test_local_changes_and_invalid_source_rejected(self):
        self.update_remote();(self.app/'main.py').write_text('LOCAL=3\n')
        self.assertEqual(self.apply()['state'],'failed')
        self.assertEqual((self.app/'main.py').read_text(),'LOCAL=3\n');self.assertEqual(self.services,[])
        with patch.object(updater,'REMOTE_URLS',{'https://github.com/famnex/luna-tibber.git'}):
            with self.assertRaises(updater.UpdateError):updater.inspect_repo(self.app)
    def test_failed_checks_keep_running_version(self):
        self.update_remote('this is not python!\n')
        self.assertEqual(self.apply()['state'],'failed')
        self.assertEqual(updater.revision(self.app),self.old);self.assertEqual(self.services,[])
    def test_failed_health_check_rolls_back(self):
        new=self.update_remote()
        def health(folder,sha,*args):
            if sha==new:raise updater.UpdateError('Testfehler beim Neustart')
        status=self.apply(health)
        self.assertEqual(status['state'],'failed');self.assertIn('wiederhergestellt',status['message'])
        self.assertEqual(updater.revision(self.app),self.old)
        self.assertEqual(self.services,['stop','start','stop','start'])
    def test_active_controller_blocks_update(self):
        self.update_remote()
        with (self.app/'controller.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.apply()['state'],'failed')
        self.assertEqual(updater.revision(self.app),self.old);self.assertEqual(self.services,[])
    def test_venv_switch_and_restore_preserves_original(self):
        old=self.app/'.venv';old.mkdir();(old/'sentinel').write_text('old')
        new=self.app/'.updates'/'venv-new';new.mkdir(parents=True);(new/'sentinel').write_text('new')
        backup=updater.switch_venv(self.app,new,'a'*32)
        self.assertEqual((old/'sentinel').read_text(),'new')
        updater.restore_venv(self.app,backup)
        self.assertFalse(old.is_symlink());self.assertEqual((old/'sentinel').read_text(),'old')
    def test_unchanged_dependencies_reuse_environment(self):
        current=self.app/'.venv/bin/python';current.parent.mkdir(parents=True);current.touch()
        with patch.object(updater,'run',side_effect=['0','']) as run:
            python,venv=updater.prepare_python(self.app,self.seed,'b'*32,None)
        self.assertEqual(python,current);self.assertIsNone(venv)
        self.assertEqual(run.call_count,2)
        self.assertEqual(run.call_args.args[0],[current,'-m','pip','check'])

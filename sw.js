'use strict';
const CACHE='luna-offline-v1';
self.addEventListener('install',event=>{event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(['/offline.html','/icon-192.png'])));self.skipWaiting();});
self.addEventListener('activate',event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k.startsWith('luna-offline-')&&k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim())));
self.addEventListener('fetch',event=>{
 // Never cache API results or queue control commands. Offline has no controls.
 if(event.request.method==='GET'&&new URL(event.request.url).origin===self.location.origin&&new URL(event.request.url).pathname==='/icon-192.png'){event.respondWith(fetch(event.request).catch(()=>caches.match('/icon-192.png')));return;}
 if(event.request.mode==='navigate'&&event.request.method==='GET')event.respondWith(fetch(event.request).catch(()=>caches.match('/offline.html')));
});
self.addEventListener('push',event=>{
 let data={};try{data=event.data.json();}catch{}
 event.waitUntil(self.registration.showNotification(data.title||'LUNA',{body:data.body||'Neue Meldung in deiner App.',icon:'/icon-192.png',badge:'/icon-192.png',tag:data.tag||'luna',renotify:false,data:{url:'/'}}));
});
self.addEventListener('notificationclick',event=>{event.notification.close();event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(async clients=>{const client=clients.find(c=>new URL(c.url).origin===self.location.origin);if(client){await client.focus();return;}return self.clients.openWindow('/');}));});

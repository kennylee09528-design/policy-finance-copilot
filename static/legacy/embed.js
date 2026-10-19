/* 嵌入模式：在工作台中以 iframe 复用原型页面（M1/M2/M3 一期为演示原型） */
(function(){
  var embed = /[?&]embed=1/.test(location.search);
  function go(){
    var v = (location.hash||'').replace('#','');
    if(embed){
      var s=document.querySelector('.sidebar'); if(s) s.style.display='none';
      var t=document.querySelector('.topbar'); if(t) t.style.display='none';
      document.body.style.background='#f4f5f7';
    }
    if(v){ var b=document.querySelector('.nav-item[data-view="'+v+'"]'); if(b) b.click(); }
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', function(){ setTimeout(go,50); });
  else setTimeout(go,50);
  window.addEventListener('hashchange', go);
})();

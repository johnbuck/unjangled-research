const viewport=document.querySelector('.deck-viewport');
const track=document.querySelector('.deck-track');
const slides=[...document.querySelectorAll('.slide')];
const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const notesBox=document.getElementById('notes');
const notesList=document.getElementById('notes-list');
const notesBtn=document.getElementById('notes-toggle');

function countUp(slide){
  slide.querySelectorAll('[data-count]').forEach(el=>{
    const target=parseFloat(el.dataset.count), dec=parseInt(el.dataset.dec||'0',10), suf=el.dataset.suffix||'';
    const fmt=v=>v.toFixed(dec)+suf;
    if(reduce){el.textContent=fmt(target);return;}
    const t0=performance.now(), dur=1300, delay=450;
    el.textContent=fmt(0);
    const step=now=>{const p=Math.min(1,Math.max(0,(now-t0-delay)/dur)); const e=1-Math.pow(1-p,3); el.textContent=fmt(target*e); if(p<1) requestAnimationFrame(step);};
    requestAnimationFrame(step);
  });
}
function renderNotes(slide){
  const parts=(slide.dataset.notes||'').split('|').filter(Boolean);
  notesList.replaceChildren(...parts.map(p=>{const li=document.createElement('li'); li.textContent=p; return li;}));
}
function activate(slide){
  slides.forEach(s=>s.classList.remove('is-active'));
  void slide.offsetWidth;
  slide.classList.add('is-active');
  countUp(slide); renderNotes(slide);
}

let i=-1;
let navigationVersion=0;
let slideTransition=Promise.resolve(true);
const setActive=n=>{
  const nextIndex=Math.max(0,Math.min(slides.length-1,n));
  if(nextIndex===i) return slideTransition;
  i=nextIndex;
  const requestedVersion=++navigationVersion;
  slideTransition=new Promise(resolve=>{
    const finish=()=>{clearTimeout(timeout);track.removeEventListener('transitionend',handleTransitionEnd);resolve(requestedVersion===navigationVersion&&i===nextIndex);};
    const handleTransitionEnd=event=>{if(event.target===track&&event.propertyName==='transform') finish();};
    const timeout=setTimeout(finish,350);
    track.addEventListener('transitionend',handleTransitionEnd);
  });
  track.style.setProperty('--i',i);
  document.querySelector('#counter')?.replaceChildren(`${i+1} / ${slides.length}`);
  activate(slides[i]);
  return slideTransition;
};
const toggleFullscreen=()=>document.fullscreenElement?document.exitFullscreen():viewport?.requestFullscreen?.();
addEventListener('keydown',e=>{
  if(e.target instanceof Element&&(e.target.isContentEditable||e.target.closest('input, select, textarea'))) return;
  if(e.key==='ArrowRight'||e.key==='PageDown') setActive(i+1);
  else if(e.key==='ArrowLeft'||e.key==='PageUp') setActive(i-1);
  else if(e.key==='Home') setActive(0);
  else if(e.key==='End') setActive(slides.length-1);
  else if(e.key==='f'||e.key==='F') toggleFullscreen();
  else if(e.key==='r'||e.key==='R') activate(slides[i]);
  else if(e.key==='n'||e.key==='N') notesBtn.click();
});
document.getElementById('prev').addEventListener('click',()=>setActive(i-1));
document.getElementById('next').addEventListener('click',()=>setActive(i+1));
document.getElementById('fullscreen').addEventListener('click',toggleFullscreen);
document.getElementById('replay').addEventListener('click',()=>activate(slides[i]));
notesBtn.addEventListener('click',()=>{const open=notesBox.hidden; notesBox.hidden=!open; notesBtn.setAttribute('aria-expanded',String(open));});

setActive(0);

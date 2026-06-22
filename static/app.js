const fmtTime = value => value ? new Date(value).toLocaleTimeString([], {hour:"numeric",minute:"2-digit"}) : "";
const fmtDate = value => value ? new Date(value).toLocaleDateString([], {weekday:"short",month:"short",day:"numeric"}) : "";
const row = (left,right,tag=false) => `<div class="row"><strong>${left}</strong><span class="${tag?"tag":""}">${right}</span></div>`;
const localDateKey = value => { const d=new Date(value); return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; };
const scheduleRow = (event,level) => `<div class="row schedule-row schedule-level-${level}"><strong>${event.title}</strong><span class="tag">${fmtDate(event.start)} | ${fmtTime(event.start)} | ${event.location}</span></div>`;
const workoutSections = sections => sections.map(s=>`<div class="workout-section"><strong>${s.name}</strong>${s.cue?`<span>${s.cue}</span>`:""}<ul>${s.items.map(i=>`<li>${i}</li>`).join("")}</ul></div>`).join("");
const workoutLayout = sections => {
  const itemCount=sections.reduce((total,section)=>total+section.items.length,0);
  if(sections.length<=3&&itemCount<=10) return "workout-layout-light";
  if(sections.length<=4&&itemCount<=18) return "workout-layout-medium";
  return "workout-layout-heavy";
};
let dashboardData=null,calendarView="today";
const sleepKey = "lifehub-screen-sleeping";
const timeline = (items, generatedAt) => {
  const now=new Date(generatedAt);
  const start=new Date(now); start.setHours(5,0,0,0);
  const finish=new Date(start); finish.setHours(finish.getHours()+22);
  const span=finish-start;
  const hours=Array.from({length:12},(_,index)=>5+index*2);
  const grid=hours.map(hour=>{
    const top=Math.min(99,(hour-5)/22*100), label=hour>24?hour-24:hour;
    return `<div class="calendar-hour" style="top:${top}%"><span>${label===24?12:label}:00</span></div>`;
  }).join("");
  const blocks=items.map(item=>{
    const itemStart=new Date(item.start),itemEnd=new Date(item.end);
    if(itemEnd<=start||itemStart>=finish) return "";
    const visibleStart=new Date(Math.max(start,itemStart)),visibleEnd=new Date(Math.min(finish,itemEnd));
    const top=(visibleStart-start)/span*100,height=Math.max(5,(visibleEnd-visibleStart)/span*100);
    const active=itemStart<=now&&now<itemEnd;
    return `<div class="calendar-event ${item.category} ${active?"active":""}" style="top:${top}%;height:${height}%"><strong>${item.title}</strong><span>${fmtTime(item.start)} - ${fmtTime(item.end)}${active?" | Now":""}</span></div>`;
  }).join("");
  const nowLine=now>=start&&now<=finish?`<div class="calendar-now" style="top:${(now-start)/span*100}%"><span>Now</span></div>`:"";
  return `<div class="calendar-day"><div class="calendar-hours">${grid}</div><div class="calendar-events">${blocks}${nowLine}</div></div>`;
};
const weekBlock = item => {
  const day=new Date(item.start);
  const start=new Date(day); start.setHours(5,0,0,0);
  const finish=new Date(start); finish.setHours(finish.getHours()+22);
  const itemStart=new Date(item.start),itemEnd=new Date(item.end);
  if(itemEnd<=start||itemStart>=finish) return "";
  const span=finish-start,visibleStart=new Date(Math.max(start,itemStart)),visibleEnd=new Date(Math.min(finish,itemEnd));
  const top=(visibleStart-start)/span*100,height=Math.max(4,(visibleEnd-visibleStart)/span*100);
  return `<div class="week-event ${item.category}" style="top:${top}%;height:${height}%"><strong>${item.title}</strong><span>${fmtTime(item.start)} - ${fmtTime(item.end)}</span></div>`;
};
const weekCalendar = days => {
  const hours=Array.from({length:12},(_,index)=>5+index*2);
  const grid=hours.map(hour=>{
    const label=((hour-1)%12)+1;
    return `<div class="week-hour" style="top:${(hour-5)/22*100}%"><span>${label}:00</span></div>`;
  }).join("");
  return `<div class="week-calendar"><div class="week-time-rail">${grid}</div>${days.map(day=>`<div class="week-day ${day.is_today?"today":""}"><div class="week-day-heading"><strong>${day.label}</strong><span>${new Date(day.date+"T12:00:00").toLocaleDateString([],{month:"numeric",day:"numeric"})}</span></div><div class="week-day-grid">${grid}${day.items.map(weekBlock).join("")}${day.items.length?"":"<em>Open day</em>"}</div></div>`).join("")}</div>`;
};
function renderCalendar(){
  if(!dashboardData) return;
  const week=calendarView==="week";
  document.querySelector("#timeline-title").textContent=week?"WEEK CALENDAR":"TODAY TIMELINE";
  document.querySelector("#show-today").classList.toggle("active",!week);
  document.querySelector("#show-week").classList.toggle("active",week);
  document.querySelector("#timeline").innerHTML=week?weekCalendar(dashboardData.week_calendar):timeline(dashboardData.timeline,dashboardData.generated_at);
}

async function post(url, body={}) { await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}); await refresh(); }
function checklist(group, items, completed, cardId) {
  const done = new Set(completed); const ratio = items.length ? done.size/items.length : 1;
  const card=document.querySelector(cardId); card.classList.remove("progress-red","progress-yellow","progress-green");
  card.classList.add(ratio===1?"progress-green":ratio>0?"progress-yellow":"progress-red");
  card.querySelector(".complete-all").textContent = ratio===1 ? "Reset" : "Done";
  card.querySelector(".complete-all").onclick=()=>post("/api/checklist/group",{group,ids:items.map(i=>i.id),complete:ratio!==1});
  return items.length ? items.map(item=>`<div class="check-row ${done.has(item.id)?"done":""}"><button class="check" data-group="${group}" data-id="${item.id}" aria-label="Toggle ${item.label}">${done.has(item.id)?"&#10003;":""}</button><span>${item.label}</span></div>`).join("") : "<p>Nothing due.</p>";
}
function bindChecks(){ document.querySelectorAll(".check-row .check").forEach(button=>button.onclick=()=>post("/api/checklist/toggle",{group:button.dataset.group,id:button.dataset.id})); }
function setupRail() {
  const rail=document.querySelector(".dashboard-grid");
  let startX=0,startScroll=0,lastX=0,lastTime=0,velocity=0,dragging=false,animation=null;
  rail.addEventListener("dragstart",event=>event.preventDefault());
  rail.addEventListener("mousedown",event=>{
    if(event.button!==0) return;
    if(event.target.closest("button")) return;
    if(animation) cancelAnimationFrame(animation);
    dragging=true; startX=event.clientX; startScroll=rail.scrollLeft; lastX=event.clientX; lastTime=performance.now(); velocity=0;
    rail.classList.add("dragging");
    event.preventDefault();
  });
  window.addEventListener("mousemove",event=>{
    if(!dragging) return;
    const now=performance.now(), elapsed=Math.max(1,now-lastTime);
    velocity=(lastX-event.clientX)/elapsed;
    lastX=event.clientX; lastTime=now;
    rail.scrollLeft=startScroll-(event.clientX-startX);
    event.preventDefault();
  });
  window.addEventListener("mouseup",()=>{
    if(!dragging) return;
    dragging=false;
    rail.classList.remove("dragging");
    let speed=velocity*18;
    const coast=()=>{
      if(Math.abs(speed)<.15) return;
      const before=rail.scrollLeft;
      rail.scrollLeft+=speed;
      if(rail.scrollLeft===before) return;
      speed*=.94;
      animation=requestAnimationFrame(coast);
    };
    animation=requestAnimationFrame(coast);
  });
  rail.addEventListener("wheel",event=>{
    const amount=Math.abs(event.deltaX)>Math.abs(event.deltaY)?event.deltaX:event.deltaY;
    if(amount===0) return;
    rail.scrollLeft+=amount;
    event.preventDefault();
  },{passive:false});
}

async function refresh() {
  const data=await fetch("/api/dashboard").then(r=>r.json()), generated=new Date(data.generated_at);
  dashboardData=data;
  document.querySelector("#date").textContent=generated.toLocaleDateString([],{weekday:"long",month:"short",day:"numeric"});
  document.querySelector("#time").textContent=generated.toLocaleTimeString([],{hour:"numeric",minute:"2-digit"});
  document.querySelector("#sync").textContent=data.sync_status; document.querySelector("#day-status").textContent=data.day_status;
  document.querySelector("#weather").innerHTML=data.weather?`<strong>${data.weather.temperature}&deg; ${data.weather.condition}</strong><span>${data.weather.location} | H ${data.weather.today_high}&deg; L ${data.weather.today_low}&deg;</span>`:"<span>Weather awaiting sync</span>";
  document.querySelector("#now-title").textContent=data.now.title; document.querySelector("#now-detail").textContent=data.now.until?`Until ${fmtTime(data.now.until)}`:"Use this space intentionally";
  document.querySelector("#next-shift-title").textContent=data.next_shift?.title||"No upcoming shifts"; document.querySelector("#next-shift-detail").textContent=data.next_shift?`${fmtDate(data.next_shift.at)} at ${fmtTime(data.next_shift.at)} | ${data.next_shift.location}`:"Nothing scheduled";
  document.querySelector("#next-school-title").textContent=data.next_school_work?.title||"No school work"; document.querySelector("#next-school-detail").textContent=data.next_school_work?`${data.next_school_work.course} | ${data.next_school_work.due_label}`:"No upcoming Canvas assignments";
  const dates=[...new Set(data.schedule.map(e=>localDateKey(e.start)))], schedule=document.querySelector("#schedule"); schedule.style.setProperty("--schedule-count",Math.max(data.schedule.length,1)); schedule.innerHTML=data.schedule.map(e=>scheduleRow(e,Math.min(dates.indexOf(localDateKey(e.start)),3))).join("")||"<p>No upcoming items.</p>";
  const w=data.workout; document.querySelector("#workout").innerHTML=w?`<h2>${w.name}</h2><p>${w.intensity}</p>${w.is_rest_day?"":row("Recommended",w.recommended_start?fmtTime(w.recommended_start):"Backup plan")}${w.backup_plan?`<p>${w.backup_plan}</p>`:""}<div class="workout-sections ${workoutLayout(w.sections)} workout-count-${Math.min(w.sections.length,6)}">${workoutSections(w.sections)}</div>`:"<p>Rest day</p>";
  document.querySelector("#assignments").innerHTML=data.assignments.length?data.assignments.map(i=>row(`${i.course}: ${i.title}`,i.due_label,true)).join(""):"<p>No school work.</p>";
  const h=data.hydration,pct=Math.min(100,h.current_bottles/h.bottle_goal*100); document.querySelector("#hydration").innerHTML=`<span class="big-number">${h.current_bottles}/${h.bottle_goal}</span><div class="meter"><div style="width:${pct}%"></div></div><p>${h.next_checkpoint?`Next ${fmtTime(h.next_checkpoint)}`:"Goal complete"} | ${h.message}</p><button id="add-bottle" class="action-button">Log bottle</button>`; document.querySelector("#add-bottle").onclick=()=>post("/api/hydration/add");
  document.querySelector("#groceries").innerHTML=checklist("groceries",data.groceries.map(i=>({id:i.id,label:`${i.name} (${i.quantity})`})),data.checklist_state.groceries,"#grocery-card");
  document.querySelector("#chores").innerHTML=checklist("chores",data.chores.map(i=>({id:i.id,label:`${i.title} | ${i.due_at?fmtTime(i.due_at):"Today"}`})),data.checklist_state.chores,"#chores-card");
  document.querySelector("#wake-routine").innerHTML=checklist("wake_up",data.wake_up_routine.map((label,index)=>({id:`wake-${index}`,label})),data.checklist_state.wake_up,"#wake-card"); bindChecks();
  document.querySelector("#winddown").textContent=fmtTime(data.wind_down_time); document.querySelector("#sleep-plan").textContent=`Bed ${fmtTime(data.bedtime)} | Wake ${fmtTime(data.wake_up_time)}. ${data.sleep_note}`;
  document.querySelector("#alerts").innerHTML=data.alerts.filter(a=>a.level!=="normal").map(a=>`<div class="alert ${a.level}"><strong>${a.message}</strong><span>${a.action}</span></div>`).join("")||"<p>No urgent alerts.</p>";
  renderCalendar();
  document.querySelector("#conflicts").innerHTML=data.conflicts.length?data.conflicts.map(c=>`<div class="conflict ${c.level}"><strong>${c.title}</strong><span>${c.detail}</span><em>${c.suggestion}</em></div>`).join(""):"<div class=\"all-clear\"><strong>No conflicts detected</strong><span>Schedule, sleep, and workout windows fit.</span></div>";
  const t=data.tomorrow; document.querySelector("#tomorrow").innerHTML=`<h2>${fmtDate(t.date+"T12:00:00")}</h2>${row("First event",t.first_event)}${row("Workout",t.workout)}${t.workout_time?row("Workout time",fmtTime(t.workout_time),true):""}${row("Assignments",t.assignment_count)}${row("Wake up",fmtTime(t.wake_up_time))}<p>${t.workout_note}</p>`;
  const sources=data.sync_details.sources; document.querySelector("#sync-details").innerHTML=Object.entries(sources).map(([name,item])=>row(name,item.state==="fresh"?`${item.age_minutes}m ago`:item.state,true)).join("");
}
async function runCommand(command){
  const value=command.trim(),lower=value.toLowerCase(),result=document.querySelector("#command-result");
  if(!value) return;
  if(["week","show week","week calendar"].includes(lower)){
    calendarView="week"; renderCalendar(); document.querySelector("#timeline-card").scrollIntoView({behavior:"smooth",block:"nearest"}); result.textContent="Showing week calendar"; return;
  }
  if(["today","show today","today timeline"].includes(lower)){
    calendarView="today"; renderCalendar(); document.querySelector("#timeline-card").scrollIntoView({behavior:"smooth",block:"nearest"}); result.textContent="Showing today timeline"; return;
  }
  const response=await fetch("/api/command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({command:value})}).then(r=>r.json());
  result.textContent=response.message;
  await refresh();
}
function setupCalendarControls(){
  document.querySelector("#show-today").onclick=()=>{calendarView="today";renderCalendar();};
  document.querySelector("#show-week").onclick=()=>{calendarView="week";renderCalendar();};
  const form=document.querySelector("#command-form"),input=document.querySelector("#command-input");
  form.addEventListener("submit",event=>{event.preventDefault();runCommand(input.value);input.value="";});
  input.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();form.requestSubmit();}});
}
function setupLiveUpdates(){
  const status=document.querySelector("#live-status");
  const events=new EventSource("/api/events");
  events.onopen=()=>{status.textContent="Live"; status.className="live";};
  events.addEventListener("dashboard",refresh);
  events.onerror=()=>{status.textContent="Reconnecting..."; status.className="stale";};
}
function setupPhoneControls(){
  document.querySelectorAll(".phone-controls button[data-target]").forEach(button=>button.onclick=()=>{
    if(button.id==="phone-hydration") return post("/api/hydration/add");
    if(button.id==="phone-sync") return post("/api/sync");
    document.querySelector(`#${button.dataset.target}`).scrollIntoView({behavior:"smooth",block:"start"});
  });
  document.querySelector("#sync-now").onclick=()=>post("/api/sync");
}
function setupSleepOverlay(){
  const overlay=document.querySelector("#sleep-overlay"),button=document.querySelector("#sleep-screen");
  const setSleeping=sleeping=>{
    overlay.classList.toggle("active",sleeping);
    overlay.setAttribute("aria-hidden",sleeping?"false":"true");
    localStorage.setItem(sleepKey,sleeping?"1":"0");
  };
  button.onclick=()=>setSleeping(true);
  overlay.addEventListener("click",()=>setSleeping(false));
  overlay.addEventListener("touchstart",event=>{event.preventDefault();setSleeping(false);},{passive:false});
  window.addEventListener("keydown",event=>{if(event.key==="Escape"||event.key===" "||event.key==="Enter") setSleeping(false);});
  setSleeping(localStorage.getItem(sleepKey)==="1");
}
function setupReloadButton(){
  document.querySelector("#reload-page").onclick=()=>window.location.reload();
}
setupRail(); setupPhoneControls(); setupCalendarControls(); setupLiveUpdates(); setupSleepOverlay(); setupReloadButton(); refresh(); setInterval(refresh,60000);

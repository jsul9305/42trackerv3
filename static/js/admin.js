let marathons = [];

function $(id){ return document.getElementById(id); }
function val(id){ return $(id).value.trim(); }
function num(v, def){ const n = Number(v); return Number.isFinite(n) ? n : def; }
function toast(msg){ alert(msg); }

// 딥링크 빠른 이동
function openRaceLink(){
  const id = val('gotoId'); if(!id){ toast('마라톤 ID 입력'); return; }
  location.href = `/race/${encodeURIComponent(id)}`;
}
function copyRaceLink(){
  const id = val('gotoId'); if(!id){ toast('마라톤 ID 입력'); return; }
  const url = `${location.origin}/race/${id}`;
  navigator.clipboard.writeText(url).then(()=>toast('링크 복사됨')).catch(()=>prompt('복사 실패. 수동 복사:', url));
}

// URL 템플릿 검증
function checkTemplate(u){
  return u.includes('{nameorbibno}') && u.includes('{usedata}');
}

/* 1) 새 대회 추가 */
async function createMarathon(){
  const name = val('new_name');
  const total = num(val('new_total'), 21.1);
  const refresh = Math.max(5, num(val('new_refresh'), 60));
  const usedata = val('new_usedata') || null;
  const url = val('new_url');
  const event_date = val('new_event_date') || null;

  if(!name){ toast('대회명 필수'); return; }
  if(!url || !checkTemplate(url)){ toast('URL 템플릿에 {nameorbibno}, {usedata} 포함해야 합니다'); return; }

  const r = await fetch('/api/marathons', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      name, url_template:url, usedata,
      total_distance_km: total, refresh_sec: refresh, event_date
    })
  });
  if(r.ok){ 
    $('new_name').value=''; $('new_total').value='21.1';
    $('new_refresh').value='60'; $('new_usedata').value=''; $('new_url').value='';
    await loadAll(); toast('대회 추가 완료');
  } else {
    const t = await r.text().catch(()=> '오류'); toast('추가 실패\n'+t);
  }
}

/* 2) 대회 리스트 로드 & 렌더 */
async function loadAll(){
  const r = await fetch('/api/marathons'); marathons = await r.json();
  
  // ✅ 엑셀 업로드용 마라톤 선택 목록 채우기
  const select = $('marathon-select');
  select.innerHTML = '';
  if(!marathons.length){
    select.innerHTML = '<option value="">등록된 대회가 없습니다</option>';
  } else {
    for(const m of marathons){
      select.innerHTML += `<option value="${m.id}">${escapeHtml(m.name)} (ID: ${m.id})</option>`;
    }
  }

  renderList();
  // 쿼리로 특정 대회 펼치기: /admin?marathon_id=1
  const mid = new URLSearchParams(location.search).get('marathon_id');
  if(mid){ const el = document.querySelector(`[data-mid="${mid}"] details`); if(el) el.open = true; }
}

function renderList(){
  const wrap = $('list'); wrap.innerHTML = '';
  if(!marathons.length){
    wrap.innerHTML = '<div class="card small muted">등록된 대회가 없습니다.</div>'; return;
  }
  for(const m of marathons){
    const card = document.createElement('div');
    card.className = 'card'; card.dataset.mid = m.id;

    card.innerHTML = `
      <h3>${m.name}</h3>
      <div class="small">
        <span class="tag">ID ${m.id}</span>
        <span class="tag">${m.enabled ? '활성' : '비활성'}</span>
        <span class="tag">${m.total_distance_km}km</span>
        <span class="tag">${m.refresh_sec}s</span>
        ${m.event_date ? `<span class="tag" style="color:var(--accent2)">${m.event_date}</span>` : ''}
      </div>

      <div class="row" style="margin-top:10px; gap:10px;">
        <a class="btn block" href="/race/${m.id}">사용자 화면 열기</a>
        <button class="btn ghost block" onclick="copyLink(${m.id})">링크 복사</button>
      </div>

      <details style="margin-top:10px;">
        <summary>설정 편집 / 참가자 관리</summary>

        <div class="two" style="margin-top:8px;">
          <div class="field">
            <label>대회명</label>
            <input class="input" id="name_${m.id}" value="${escapeHtml(m.name)}" />
          </div>
          <div class="field">
            <label>총거리 (km)</label>
            <input class="input" id="total_${m.id}" type="number" inputmode="decimal" value="${m.total_distance_km}" />
          </div>
        </div>

        <div class="two" style="margin-top:8px;">
          <div class="field">
            <label>크롤 주기 (초)</label>
            <input class="input" id="refresh_${m.id}" type="number" inputmode="numeric" value="${m.refresh_sec}" />
          </div>
          <div class="field">
            <label>usedata (대회 ID)</label>
            <input class="input mono" id="usedata_${m.id}" value="${m.usedata ?? ''}" />
          </div>
          <div class="field">
            <label>대회 날짜 (선택)</label>
            <input class="input" id="event_date_${m.id}" type="date" value="${m.event_date ?? ''}" />
          </div>
        </div>

        <div class="field" style="margin-top:8px;">
          <label>URL 템플릿</label>
          <input class="input mono" id="url_${m.id}" value="${escapeHtml(m.url_template)}" />
          <div class="small muted">예: https://smartchip.co.kr/return_data_livephoto.asp?nameorbibno={nameorbibno}&usedata={usedata}</div>
        </div>

        <div class="row" style="margin-top:10px;">
          <select id="enabled_${m.id}" class="input" style="max-width:160px;">
            <option value="1" ${m.enabled? 'selected':''}>활성</option>
            <option value="0" ${!m.enabled? 'selected':''}>비활성</option>
          </select>
          <button class="btn primary" onclick="saveMarathon(${m.id})">저장</button>
        </div>

        <!-- ✅ 여기 아래에 '참여 코드' UI 추가 -->
        <div class="row" style="margin-top:10px;">
            <div class="field">
                <label>참여 코드</label>
                <input class="input mono" id="code_${m.id}" value="${escapeHtml(m.join_code ?? '')}"/>
            </div>
            <button class="btn ghost block" onclick="copyCode(${m.id})">코드 복사</button>
            <button class="btn ghost block" onclick="regenerateCode(${m.id})">코드 재생성</button>
        </div>
        <div class="row" style="margin-top:10px;">
            <span class="tag">딥링크:
                <a id="code_link_${m.id}"
                href="/code/${m.id}/${escapeHtml(m.join_code ?? '')}"
                target="_blank">/code/${m.id}/${escapeHtml(m.join_code ?? '')}</a>
            </span>
        </div>

        <div class="small muted" style="margin-top:8px;">
          미리보기(로컬에서 CORS로 외부 요청은 불가할 수 있음):  
          <span class="mono">${previewUrl(m.id)}</span>
        </div>

        <div style="height:8px"></div>
        <hr style="border:0; border-top:1px solid var(--border);" />

        <div class="row" style="margin-top:8px;">
          <div class="field"><label>참가자 목록</label></div>
          <div class="spacer"></div>
          <button class="btn" onclick="reloadParticipants(${m.id})">새로고침</button>
        </div>

        <div class="two" style="margin-top:6px;">
          <div class="field">
            <label>성명(표시용, 선택)</label>
            <input class="input" id="palias_${m.id}" placeholder="홍길동 (선택)" />
          </div>
          <div class="field">
            <label>배번/이름 (nameorbibno)</label>
            <input class="input" id="pbib_${m.id}" placeholder="예: 10396 또는 홍길동" />
          </div>
        </div>
        <div class="row" style="margin-top:6px;">
          <button class="btn primary" onclick="addParticipant(${m.id})">+ 참가자 추가</button>
        </div>

        <div id="plist_${m.id}" class="plist"></div>
      </details>
    `;

    wrap.appendChild(card);
    // 참가자 즉시 로드
    reloadParticipants(m.id);
    // ✅ 참여 코드 채우기 (백엔드에 /api/admin/marathons/:id/code가 있다고 가정)
    fillJoinCode(m.id);
  }
}
async function fillJoinCode(mid){
  try{
    const r = await fetch(`/api/admin/marathons/${mid}/code`);
    if(!r.ok) return;
    const d = await r.json(); // {marathon_id, join_code, expires_at}
    if(!d.join_code) return;
    const input = $(`code_${mid}`);
    const link  = $(`code_link_${mid}`);
    if (input) input.value = d.join_code;
    if (link) {
      link.href = `/code/${mid}/${escapeHtml(d.join_code)}`;
      link.textContent = `/code/${mid}/${escapeHtml(d.join_code)}`;
    }
  }catch(e){ /* 무시 */ }
}

function updateJoinLink(mid, code){
  const link  = $(`code_link_${mid}`);
  if (link) {
    link.href = `/code/${mid}/${escapeHtml(code)}`;
    link.textContent = `/code/${mid}/${escapeHtml(code)}`;
  }
}

function escapeHtml(s){
  return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'","&#039;");
}

function previewUrl(mid){
  // 카드 렌더 직후 값으로 간단 프리뷰 문자열만 구성
  const m = marathons.find(x=>x.id===mid); if(!m) return '';
  const ex = (m.url_template||'').replace('{nameorbibno}','<BIB>').replace('{usedata}', m.usedata || '<USEDATA>');
  return ex;
}

function copyLink(mid){
  const url = `${location.origin}/race/${mid}`;
  navigator.clipboard.writeText(url).then(()=>alert('링크 복사됨')).catch(()=>prompt('복사 실패. 수동 복사:', url));
}
function copyCode(mid) {
  const v = val(`code_${mid}`);
  if(!v){ return toast('코드가 비어 있습니다. 재생성부터 하세요.'); }
  navigator.clipboard.writeText(v)
    .then(()=>toast('코드 복사됨'))
    .catch(()=>prompt('복사 실패. 수동 복사:', v));
}

function regenerateCode(mid) {
  try{
    const r = await fetch(`/api/admin/marathons/${mid}/regen-join-code`, { method:'POST' });
    const d = await r.json();
    if(!r.ok || !d.join_code){ return toast(d.description || d.error || '코드 재생성 실패'); }
    const input = $(`code_${mid}`);
    if (input) input.value = d.join_code;
    updateJoinLink(mid, d.join_code);
    toast(`새 코드: ${d.join_code}`);
  }catch(e){
    toast('네트워크 오류');
  }
}
/* 저장 */
async function saveMarathon(mid){
  const name = val(`name_${mid}`);
  const total = num(val(`total_${mid}`), 21.1);
  const refresh = Math.max(5, num(val(`refresh_${mid}`), 60));
  const usedata = val(`usedata_${mid}`) || null;
  const url = val(`url_${mid}`);
  const enabled = Number(val(`enabled_${mid}`)||'1');
  const event_date = val(`event_date_${mid}`) || null;

  if(!name){ toast('대회명 필수'); return; }
  if(!url || !checkTemplate(url)){ toast('URL 템플릿에 {nameorbibno}, {usedata} 포함해야 합니다'); return; }

  const r = await fetch(`/api/marathons/${mid}`, {
    method:'PUT', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      name, url_template:url, usedata,
      total_distance_km: total, refresh_sec: refresh, enabled, event_date
    })
  });
  if(r.ok){ await loadAll(); toast('저장 완료'); }
  else{ const t = await r.text().catch(()=> '오류'); toast('저장 실패\n'+t); }
}

/* 참가자 관리 */
async function reloadParticipants(mid){
  const r = await fetch(`/api/participants?marathon_id=${mid}`);
  const list = await r.json();
  const box = $(`plist_${mid}`); box.innerHTML = '';
  if(!list.length){
    box.innerHTML = '<div class="small muted">등록된 참가자가 없습니다.</div>'; return;
  }
  for(const p of list){
    const div = document.createElement('div');
    div.className = 'pitem';
    div.innerHTML = `
      <div>
        <div><b>${escapeHtml(p.alias || '-')}</b> <span class="tag mono">#${escapeHtml(p.nameorbibno)}</span></div>
        <div class="small muted">ID ${p.id} · active=${p.active}</div>
      </div>
      <div class="row">
        <a class="btn" href="/race/${p.marathon_id}" title="해당 대회 열기">대회보기</a>
        <button class="btn danger" onclick="delParticipant(${p.id}, ${mid})">삭제</button>
      </div>
    `;
    box.appendChild(div);
  }
}

async function addParticipant(mid){
  const alias = val(`palias_${mid}`);
  const nameorbibno = val(`pbib_${mid}`);
  if(!nameorbibno){ toast('배번/이름은 필수'); return; }
  const r = await fetch('/api/participants', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ marathon_id: mid, alias, nameorbibno })
  });
  if(r.ok){ $(`pbib_${mid}`).value=''; await reloadParticipants(mid); toast('추가 완료'); }
  else{ const t=await r.text().catch(()=> '오류'); toast('추가 실패\n'+t); }
}

async function delParticipant(pid, mid){
  if(!confirm('정말 삭제할까요?')) return;
  await fetch(`/api/participants/${pid}`, {method:'DELETE'});
  await reloadParticipants(mid);
}

/* 초기 진입: ?marathon_id= 로 특정 카드 펼치기 지원 */
loadAll();

// ✅ 엑셀 업로드 폼 제출 핸들러
$('upload-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = e.target;
  const formData = new FormData(form);
  const marathonId = formData.get('marathon_id');
  const file = formData.get('file');

  if (!marathonId) {
    toast('업로드할 마라톤을 선택해주세요.');
    return;
  }
  if (!file || file.size === 0) {
    toast('업로드할 엑셀 파일을 선택해주세요.');
    return;
  }

  const r = await fetch('/api/participants/upload_excel', { method: 'POST', body: formData });
  const result = await r.json();
  toast(result.message || (result.error ? `오류: ${result.error}`: '알 수 없는 응답'));
  if(r.ok) await reloadParticipants(marathonId);
});
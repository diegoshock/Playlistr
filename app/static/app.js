'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const esc = escapeHTML;
const number = value => new Intl.NumberFormat('es').format(value);
const duration = value => `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
const date = value => value ? new Date(value).toLocaleDateString('es', {day:'numeric', month:'short', year:'numeric'}) : 'Nunca';
let state, page = 'create', preview = null, timer = null, toastTimer, currentArtist;
let playlistName = '', genreSearch = '', artistSearch = '', artistStatus = 'all';
let filters = {genres:[], mode:'any', limit:50, shuffle:true, year_from:null, year_to:null, exclude_artists:[]};
const pageLabels = {create:'Crear playlist', artists:'Artistas y géneros', playlists:'Mis playlists', settings:'Configuración'};
const statusLabels = {pending:'Pendiente de buscar', matched:'Fuente verificada', ambiguous:'Elegir artista', not_found:'Sin géneros publicados', error:'Error de consulta', manual:'Editado por ti'};

async function api(path, options = {}) {
  const response = await fetch('/api' + path, {credentials:'same-origin', ...options,
    headers:{'Content-Type':'application/json', ...(options.headers || {})}});
  let data;
  try { data = await response.json(); } catch { throw new Error('Respuesta inesperada del servidor.'); }
  if (!response.ok) {
    if (response.status === 401 && path !== '/login') showLogin();
    const detail = Array.isArray(data.detail) ? data.detail.map(item => item.msg).join('. ') : data.detail;
    throw new Error(detail || `Error HTTP ${response.status}`);
  }
  return data;
}
const post = (path, body = {}) => api(path, {method:'POST', body:JSON.stringify(body)});
function notify(message, error = false) {
  clearTimeout(toastTimer);
  const toast = $('#toast');
  toast.textContent = message;
  toast.className = 'toast' + (error ? ' error' : '');
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, error ? 12000 : 6500);
}
function showLogin() {
  $('#login').hidden = false; $('#shell').hidden = true; $('#job-banner').hidden = true;
  clearTimeout(timer); timer = null;
}
async function loadState() {
  state = await api('/state');
  $('#login').hidden = true; $('#shell').hidden = false;
  render();
  if (state.job.status === 'running') watchJob();
}
function render() {
  $('#page-label').textContent = pageLabels[page];
  document.title = `${pageLabels[page]} · Playlistr`;
  document.querySelectorAll('[data-page]').forEach(button => button.classList.toggle('active', button.dataset.page === page));
  const connection = $('#connection-badge');
  connection.textContent = state.connection.configured ? 'Navidrome configurado' : 'Conectar Navidrome';
  connection.classList.toggle('connected', state.connection.configured);
  const review = state.artists.filter(a => ['ambiguous','error'].includes(a.status)).length;
  $('#review-count').textContent = review || '';
  $('#content').innerHTML = ({create:renderCreate,artists:renderArtists,playlists:renderPlaylists,settings:renderSettings})[page]();
  applyBusy();
}
function applyBusy() {
  const busy = state.job.status === 'running';
  document.querySelectorAll('[data-idle]').forEach(button => { button.disabled = busy; });
}
function header(title, subtitle, actions = '') {
  return `<div class="page-heading"><div><h1>${title}</h1><p>${subtitle}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ''}</div>`;
}
function empty(title, text, action = '') {
  return `<div class="panel page-empty"><div class="empty-art" aria-hidden="true">♫</div><h2>${title}</h2><p>${text}</p>${action}</div>`;
}
function onboarding() {
  if (!state.connection.configured) return `<div class="checklist"><span aria-hidden="true">↗</span><div><strong>Tu música es el punto de partida.</strong><br>Conecta tu servidor Navidrome para importar la biblioteca.</div><button data-page="settings" class="button small primary">Conectar servidor →</button></div>`;
  if (!state.stats.songs) return `<div class="checklist"><span aria-hidden="true">↻</span><div><strong>La conexión está guardada.</strong><br>Importa los artistas y canciones de tu biblioteca.</div><button data-action="sync" data-idle class="button small primary">Sincronizar biblioteca</button></div>`;
  if (!state.stats.classified) return `<div class="checklist"><span aria-hidden="true">◎</span><div><strong>Ahora vamos por los géneros.</strong><br>Busca información pública de tus ${number(state.stats.artists)} artistas.</div><button data-action="enrich" data-idle class="button small primary">Buscar géneros</button></div>`;
  return '';
}
function renderCreate() {
  const stats = [['♫', state.stats.songs, 'Canciones en biblioteca'],['♬', state.stats.artists, 'Artistas descubiertos'],['◎', state.stats.genres, 'Géneros disponibles'],['▤', state.stats.playlists, 'Playlists creadas']];
  return header('Crea tu próxima favorita', 'Redescubre tu biblioteca, una mezcla a la vez.', state.connection.configured ? '<button data-action="sync" data-idle class="button">↻ Sincronizar</button>' : '') +
    `<section class="hero"><div class="hero-copy"><span class="eyebrow">BUENA MÚSICA. MEJORES CONEXIONES.</span><h2>Tu biblioteca.<br><em>Infinitas combinaciones.</em></h2><p>Elige un género, encuentra tu mezcla y llévala a Navidrome.<br>Basado en artistas reales y fuentes que puedes consultar.</p></div><div class="hero-art" aria-hidden="true">${'<i></i>'.repeat(9)}</div></section>
    <section class="stats" aria-label="Resumen de biblioteca">${stats.map(([icon,count,label]) => `<div class="stat"><span class="stat-icon" aria-hidden="true">${icon}</span><div><strong>${number(count)}</strong><small>${label}</small></div></div>`).join('')}</section>
    ${onboarding()}
    <div class="builder-grid"><section class="panel"><div class="panel-heading"><h2><span class="step-number">01</span> Diseña tu mezcla</h2><small>A tu manera</small></div><div class="panel-body">
    <label for="playlist-name">Nombre de la playlist</label><input id="playlist-name" maxlength="120" placeholder="Ej. Indie para perderse un rato" value="${esc(playlistName)}">
    <div class="label-line"><label for="genre-search">Géneros musicales</label><button class="text-button" data-action="clear-genres">Limpiar selección</button></div>
    <div class="input-with-icon"><span aria-hidden="true">⌕</span><input id="genre-search" type="search" placeholder="Encuentra un género…" value="${esc(genreSearch)}"></div>
    <div id="genre-chips" class="chips">${renderGenres()}</div>
    <p class="hint">${state.stats.genres ? 'Sin selección se incluyen todos los géneros, también canciones sin clasificar.' : 'Los géneros aparecerán después de consultar tus artistas.'}</p>
    <label for="genre-mode">Combinar géneros</label><select id="genre-mode"><option value="any" ${filters.mode === 'any' ? 'selected':''}>Cualquiera de los seleccionados</option><option value="all" ${filters.mode === 'all' ? 'selected':''}>Todos los seleccionados</option></select>
    <div class="form-row"><div><label for="year-from">Desde el año</label><input id="year-from" type="number" min="1000" max="3000" placeholder="Sin límite" value="${filters.year_from || ''}"></div><div><label for="year-to">Hasta el año</label><input id="year-to" type="number" min="1000" max="3000" placeholder="Sin límite" value="${filters.year_to || ''}"></div></div>
    <div class="form-row"><div><label for="track-limit">Máximo de canciones</label><input id="track-limit" type="number" min="1" max="2000" value="${filters.limit}"></div><div><label for="exclude-artist">Excluir un artista</label><select id="exclude-artist"><option value="">Ninguno</option>${state.artists.map(a => `<option value="${esc(a.id)}" ${filters.exclude_artists.includes(a.id) ? 'selected':''}>${esc(a.name)}</option>`).join('')}</select></div></div>
    <div class="switch-row"><label for="shuffle">Que la mezcla me sorprenda<small>Orden aleatorio en cada vista previa</small></label><input id="shuffle" class="toggle" type="checkbox" role="switch" ${filters.shuffle ? 'checked':''}></div>
    <button data-action="preview" class="button primary full-width" ${!state.stats.songs ? 'disabled':''}>✦ Generar vista previa</button>
    <div class="subtle-box">ⓘ Clasificamos por el género del artista, no por el audio de cada canción. Puedes revisar las fuentes y corregir cualquier género.</div>
    </div></section><section class="panel" id="preview-panel">${renderPreview()}</section></div>`;
}
function renderGenres() {
  const list = state.genres.filter(g => g.name.toLowerCase().includes(genreSearch.toLowerCase()));
  return list.length ? list.map(g => `<button class="chip ${filters.genres.includes(g.name) ? 'selected':''}" aria-pressed="${filters.genres.includes(g.name)}" data-genre="${esc(g.name)}">${esc(g.name)}${filters.genres.includes(g.name) ? ' ✓':`<span class="chip-count">${g.artists}</span>`}</button>`).join('') : `<span class="hint">${state.genres.length ? 'No hay géneros con ese nombre.' : 'Tu próxima mezcla empieza conectando tu música.'}</span>`;
}
function renderPreview() {
  let result = `<div class="panel-heading"><h2><span class="step-number">02</span> Tu próxima playlist</h2><small>Vista previa</small></div>`;
  if (!preview) return result + `<div class="preview-empty"><div class="empty-art" aria-hidden="true">♫</div><h3>Un buen descubrimiento te espera</h3><p>Elige tus géneros y genera una vista previa.<br>Tu selección aparecerá aquí antes de guardarla.</p></div><div class="preview-bottom"><small>Escucha desde tu reproductor Navidrome</small><span class="muted" aria-hidden="true">↗</span></div>`;
  if (!preview.songs.length) return result + `<div class="preview-empty"><div class="empty-art" aria-hidden="true">⌕</div><h3>No encontramos esa combinación</h3><p>Prueba con otros géneros, amplía los años o revisa los artistas que aún no tienen clasificación.</p></div>`;
  result += `<div class="preview-summary"><span>${number(preview.songs.length)} canciones · ${Math.round(preview.duration / 60)} min</span><span>${number(preview.total_matches)} coincidencias</span></div><div class="track-list">`;
  result += preview.songs.map((song,index) => `<div class="track"><span class="track-index">${index + 1}</span><span class="track-cover" aria-hidden="true">♫</span><div class="track-name" title="${esc(song.title)}">${esc(song.title)}<small>${esc(song.artist)} · ${esc(song.album)}</small></div><span class="track-duration">${duration(song.duration)}</span><button type="button" class="track-remove" data-remove-song="${esc(song.id)}" aria-label="Quitar ${esc(song.title)} de la playlist" title="Quitar de la playlist">×</button></div>`).join('');
  return result + `</div><div class="preview-bottom"><small>Se guardarán estas mismas canciones.<br>Vista previa válida durante 15 minutos.</small><button data-action="save-playlist" data-idle class="button primary">Guardar en Navidrome ↗</button></div>`;
}
function renderArtists() {
  const actions = state.stats.artists ? `<button data-action="enrich" data-idle class="button primary">◎ Buscar pendientes</button><button data-action="refresh-genres" data-idle class="button">Actualizar fuentes</button>` : '';
  return header('Artistas y géneros', 'Cada etiqueta tiene una historia. Consulta su fuente y afina tu biblioteca.',actions) + onboarding() +
    (state.artists.length ? `<div class="artists-toolbar"><input id="artist-search" type="search" aria-label="Buscar artista" placeholder="Buscar en tus artistas…" value="${esc(artistSearch)}"><select id="artist-status" aria-label="Filtrar por estado"><option value="all">Todos los artistas</option><option value="review" ${artistStatus === 'review' ? 'selected':''}>Necesitan revisión</option><option value="classified" ${artistStatus === 'classified' ? 'selected':''}>Con géneros</option><option value="pending" ${artistStatus === 'pending' ? 'selected':''}>Pendientes</option></select></div><div id="artist-grid" class="artist-grid">${renderArtistCards()}</div><p class="hint">${state.stats.classified} de ${state.stats.artists} artistas con géneros. Las correcciones manuales se conservan al actualizar fuentes.</p>` : empty('Artistas con identidad propia','Sincroniza Navidrome para empezar. No usaremos las etiquetas de los archivos como si fueran una fuente externa.'));
}
function renderArtistCards() {
  const artists = state.artists.filter(a => a.name.toLowerCase().includes(artistSearch.toLowerCase()) &&
    (artistStatus === 'all' || (artistStatus === 'review' && (['ambiguous','error','not_found'].includes(a.status) || a.error)) ||
     (artistStatus === 'classified' && a.genres.length) || (artistStatus === 'pending' && a.status === 'pending')));
  return artists.length ? artists.map(a => `<button class="artist-card" data-artist="${esc(a.id)}"><div class="artist-top"><span class="avatar" aria-hidden="true">${esc(a.name.split(' ').slice(0,2).map(n => n[0]).join('').toUpperCase())}</span><div><h3>${esc(a.name)}</h3><small>${number(a.song_count)} canciones</small></div></div><div class="artist-tags">${a.genres.length ? a.genres.slice(0,4).map(g => `<span class="tag">${esc(g)}</span>`).join('') + (a.genres.length > 4 ? `<span class="tag">+${a.genres.length - 4}</span>`:'') : '<span class="hint">Sin géneros asignados</span>'}</div><div class="artist-status"><span class="${['ambiguous','error'].includes(a.status) || a.error ? 'status-warning':''}">${esc(a.error ? 'Revisar consulta' : statusLabels[a.status])}</span><span>Ver detalles ↗</span></div></button>`).join('') : '<p class="hint">Ningún artista coincide con estos filtros.</p>';
}
function renderPlaylists() {
  return header('Tus mezclas, a mano', 'Playlists creadas desde Playlistr y enviadas a tu cuenta de Navidrome.', '<button data-page="create" class="button primary">+ Crear playlist</button>') +
    (state.playlists.length ? `<div class="playlist-grid">${state.playlists.map(p => `<article class="panel playlist-card"><div class="playlist-art" aria-hidden="true">♫</div><div class="panel-body"><h3>${esc(p.name)}</h3><p>${number(p.song_count)} canciones · ${date(p.created_at)}</p><span class="pill">Guardada en Navidrome ✓</span></div></article>`).join('')}</div><p class="hint">Historial local de creaciones. Las ediciones o eliminaciones posteriores en Navidrome no se reflejan aquí.</p>` : empty('La primera es siempre especial','Crea una mezcla por géneros y guárdala. Aparecerá en tu cuenta de Navidrome, lista para escuchar.','<button data-page="create" class="button primary">Crear mi primera playlist →</button>'));
}
function renderSettings() {
  const c = state.connection;
  return header('Todo en su sitio', 'Conecta tu biblioteca y deja que tu música haga el resto.') + `<div class="settings-layout"><section class="panel"><div class="panel-heading"><h2>◎ Conexión con Navidrome</h2><small>${c.configured ? 'Configurada':'Primer paso'}</small></div><form id="connection-form" class="panel-body settings-form"><label for="server-url">Dirección del servidor</label><input id="server-url" type="url" required placeholder="http://192.168.1.100:4533" value="${esc(c.url)}"><p class="hint">Usa la IP de Unraid o el nombre del contenedor en una red Docker compartida. “localhost” apunta a Playlistr.</p><label for="server-user">Usuario de Navidrome</label><input id="server-user" required autocomplete="username" value="${esc(c.username)}" placeholder="Tu usuario"><label for="server-password">Contraseña de Navidrome</label><input id="server-password" type="password" autocomplete="current-password" ${c.configured ? '':'required'} placeholder="${c.configured ? 'Dejar vacía para conservar la actual':'Contraseña de tu cuenta'}"><p class="hint">Se guarda cifrada en el volumen de datos. No se envía a MusicBrainz ni a Wikidata.</p><button type="submit" class="button primary full-width" data-idle>Probar conexión y guardar →</button><p class="hint">Cambiar de servidor o de usuario borra la caché local y el historial de esta instalación; las playlists de Navidrome se conservan.</p><hr><p class="hint">Última sincronización: ${date(state.last_sync)}</p>${c.configured ? '<button type="button" data-action="sync" data-idle class="button full-width">↻ Sincronizar biblioteca</button>':''}</form></section><section class="panel"><div class="panel-heading"><h2>Sin adivinar tu música</h2></div><div class="panel-body"><ol class="info-list"><li><strong>Identificamos al artista.</strong><br>Primero usamos su ID de MusicBrainz si Navidrome lo proporciona. Después buscamos el nombre y revisamos las coincidencias.</li><li><strong>Consultamos fuentes públicas.</strong><br>MusicBrainz aporta géneros votados por su comunidad. Si no tiene géneros, buscamos la propiedad musical en su entidad enlazada de Wikidata.</li><li><strong>La decisión final es tuya.</strong><br>Los homónimos se muestran para revisión. Puedes corregir géneros sin modificar los archivos musicales.</li></ol><div class="subtle-box">La búsqueda envía nombres de artistas a MusicBrainz e identificadores a Wikidata. No envía audio, contraseñas ni tu biblioteca completa. No requiere claves API.</div><p class="hint">Los géneros describen artistas: sus discos y canciones pueden pertenecer a estilos diferentes. No se realiza análisis de audio.</p><hr><button data-action="logout" class="button">Cerrar sesión</button></div></section></div>`;
}
function invalidatePreview() {
  preview = null;
  if ($('#preview-panel')) $('#preview-panel').innerHTML = renderPreview();
}
function readFilters() {
  filters.mode = $('#genre-mode').value;
  filters.limit = Number($('#track-limit').value);
  filters.year_from = $('#year-from').value ? Number($('#year-from').value) : null;
  filters.year_to = $('#year-to').value ? Number($('#year-to').value) : null;
  filters.shuffle = $('#shuffle').checked;
  filters.exclude_artists = $('#exclude-artist').value ? [$('#exclude-artist').value] : [];
  if (!Number.isInteger(filters.limit) || filters.limit < 1 || filters.limit > 2000) throw new Error('Elige entre 1 y 2000 canciones.');
  if (filters.year_from && filters.year_to && filters.year_from > filters.year_to) throw new Error('El año inicial debe ser menor o igual al final.');
}
async function startJob(path, body = {}) {
  state.job = await post(path, body);
  applyBusy(); watchJob();
}
function watchJob() {
  clearTimeout(timer);
  const banner = $('#job-banner');
  banner.hidden = false;
  banner.textContent = state.job.message + (state.job.total ? ` · ${state.job.done}/${state.job.total}` : '');
  timer = setTimeout(async () => {
    try {
      state.job = await api('/job');
      if (state.job.status === 'running') { watchJob(); return; }
      banner.hidden = true;
      if (state.job.kind === 'sync') preview = null;
      if (state.job.status === 'failed') notify(state.job.message, true);
      else if (state.job.errors) notify(`Consulta terminada con ${state.job.errors} errores. Revisa los detalles de los artistas.`, true);
      else notify(state.job.kind === 'sync' ? 'Biblioteca sincronizada. Ya puedes buscar géneros.' : 'Consulta completada. Revisa tus artistas y géneros.');
      await loadState();
    } catch (error) {
      banner.hidden = true;
      notify(error.message, true);
      // Transient errors do not abandon a running job; expired sessions do.
      if (!$('#shell').hidden) timer = setTimeout(watchJob, 4000);
    }
  }, 1500);
}
function openArtist(id) {
  currentArtist = state.artists.find(a => a.id === id);
  if (!currentArtist) return;
  const a = currentArtist;
  $('#artist-dialog-content').innerHTML = `<div class="dialog-header"><div><h2 id="artist-dialog-title">${esc(a.name)}</h2><p>${number(a.song_count)} canciones · ${esc(statusLabels[a.status])}</p></div><button class="close-button" data-action="close-dialog" aria-label="Cerrar">×</button></div>${a.error ? `<p class="error-text hint">${esc(a.error)}</p>`:''}
  <div class="chips">${a.genres.map(g => `<span class="tag">${esc(g)}</span>`).join('')}</div>
  <div class="dialog-section"><h3>Fuentes de la clasificación</h3>${a.evidence.length ? a.evidence.map(e => `<div class="evidence">${e.url && /^https:\/\/(musicbrainz\.org|www\.wikidata\.org)\//.test(e.url) ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.source)} ↗</a>`:esc(e.source)}<p>${e.genres.length ? esc(e.genres.join(' · ')):'Sin géneros publicados en esta fuente.'}</p>${e.votes && Object.keys(e.votes).length ? `<p>Votos de la comunidad: ${esc(Object.entries(e.votes).map(([g,v])=>`${g} (${v})`).join(', '))}</p>`:''}</div>`).join(''):'<p class="hint">Todavía no hay una fuente asignada. Busca los géneros o elige un artista.</p>'}<p class="hint">Última clasificación: ${date(a.checked_at)}</p></div>
  ${a.candidates.length ? `<div class="dialog-section"><h3>¿Cuál de estos artistas es?</h3><p class="hint">Comprueba país y descripción antes de elegir. Si ninguno coincide, asigna los géneros manualmente.</p>${a.candidates.map(c => `<button class="candidate" data-mbid="${esc(c.id)}"><span>${esc(c.name)}<small>${esc([c.description,c.country].filter(Boolean).join(' · ') || 'Sin información adicional')}</small></span><span>Elegir →</span></button>`).join('')}</div>`:''}
  <form id="manual-genre-form" class="dialog-section"><label for="manual-genres">Ajustar géneros manualmente</label><textarea id="manual-genres" placeholder="alternative rock, indie rock">${esc(a.genres.join(', '))}</textarea><p class="hint">Separa los géneros con comas. Tu selección no se sobrescribe al actualizar fuentes.</p><button class="button primary" data-idle type="submit">Guardar mis géneros</button></form>`;
  applyBusy();
  $('#artist-dialog').showModal();
}
async function logout() {
  await post('/logout');
  state = null; preview = null; showLogin();
}

document.addEventListener('click', async event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  if (button.dataset.removeSong) {
    const removed = preview?.songs.find(song => song.id === button.dataset.removeSong);
    if (!removed) return;
    preview.songs = preview.songs.filter(song => song.id !== removed.id);
    preview.duration = preview.songs.reduce((total, song) => total + song.duration, 0);
    $('#preview-panel').innerHTML = renderPreview(); applyBusy();
    return;
  }
  if (button.dataset.page) { page = button.dataset.page; render(); return; }
  if (button.dataset.genre) {
    const g = button.dataset.genre;
    filters.genres = filters.genres.includes(g) ? filters.genres.filter(v => v !== g) : [...filters.genres,g];
    $('#genre-chips').innerHTML = renderGenres(); invalidatePreview(); return;
  }
  if (button.dataset.artist) { openArtist(button.dataset.artist); return; }
  const action = button.dataset.action;
  if (!action && !button.dataset.mbid && button.id !== 'logout') return;
  button.disabled = true;
  try {
    if (action === 'sync') await startJob('/sync');
    else if (action === 'enrich' || action === 'refresh-genres') await startJob('/enrich', {refresh:action === 'refresh-genres'});
    else if (action === 'clear-genres') { filters.genres = []; $('#genre-chips').innerHTML = renderGenres(); invalidatePreview(); }
    else if (action === 'preview') {
      readFilters();
      preview = await post('/preview', filters);
      $('#preview-panel').innerHTML = renderPreview(); applyBusy();
    } else if (action === 'save-playlist') {
      if (!playlistName.trim()) { $('#playlist-name').focus(); throw new Error('Ponle un nombre a tu playlist antes de guardarla.'); }
      await post('/playlists', {name:playlistName, preview_id:preview.preview_id, song_ids:preview.songs.map(song => song.id)});
      notify(`“${playlistName}” ya está en Navidrome.`);
      preview = null; playlistName = ''; page = 'playlists'; await loadState();
    } else if (action === 'close-dialog') $('#artist-dialog').close();
    else if (button.dataset.mbid) {
      await startJob(`/artists/${encodeURIComponent(currentArtist.id)}/resolve`, {mbid:button.dataset.mbid});
      $('#artist-dialog').close();
    } else if (action === 'logout' || button.id === 'logout') await logout();
  } catch (error) { notify(error.message, true); }
  finally { button.disabled = false; if (state) applyBusy(); }
});
document.addEventListener('input', event => {
  const {id,value} = event.target;
  if (id === 'playlist-name') playlistName = value;
  if (id === 'genre-search') { genreSearch = value; $('#genre-chips').innerHTML = renderGenres(); }
  if (id === 'artist-search') { artistSearch = value; $('#artist-grid').innerHTML = renderArtistCards(); }
  if (['year-from','year-to','track-limit'].includes(id)) { try { readFilters(); } catch {} invalidatePreview(); }
});
document.addEventListener('change', event => {
  if (event.target.id === 'artist-status') { artistStatus = event.target.value; $('#artist-grid').innerHTML = renderArtistCards(); }
  if (['genre-mode','shuffle','exclude-artist'].includes(event.target.id)) { try { readFilters(); } catch {} invalidatePreview(); }
});
document.addEventListener('submit', async event => {
  event.preventDefault();
  const form = event.target, button = form.querySelector('[type="submit"]');
  button.disabled = true;
  try {
    if (form.id === 'login-form') {
      $('#login-error').textContent = '';
      await post('/login', {password:$('#login-password').value});
      $('#login-password').value = ''; await loadState();
    } else if (form.id === 'connection-form') {
      const body = {url:$('#server-url').value.trim().replace(/\/+$/,''),username:$('#server-user').value.trim(),password:$('#server-password').value};
      if (state.connection.configured && (body.url !== state.connection.url || body.username !== state.connection.username) &&
          !confirm('Cambiar la conexión eliminará la caché local, las correcciones de géneros y el historial local. Tus playlists de Navidrome se conservan. ¿Continuar?')) return;
      await post('/connection', body);
      preview = null; filters.genres = []; filters.exclude_artists = [];
      notify('Conexión comprobada y guardada. Ya puedes sincronizar.'); await loadState();
    } else if (form.id === 'manual-genre-form') {
      await api(`/artists/${encodeURIComponent(currentArtist.id)}`, {method:'PUT',body:JSON.stringify({genres:$('#manual-genres').value.split(',')})});
      $('#artist-dialog').close(); invalidatePreview(); notify('Géneros actualizados.'); await loadState();
    }
  } catch (error) {
    if (form.id === 'login-form') $('#login-error').textContent = error.message;
    else notify(error.message, true);
  } finally { button.disabled = false; if (state) applyBusy(); }
});

loadState().catch(error => { showLogin(); if (!error.message.includes('Inicia sesión')) $('#login-error').textContent = error.message; });

"""Browser-level Engineering Intelligence Command Center for Streamlit."""
from __future__ import annotations

import json

import streamlit.components.v1 as components

from src.core.command_registry import command_payload


def render_command_center(*, current_page: str = "Dashboard", user_name: str = "Engineer") -> None:
    """Mount the global Ctrl/Command+K command palette into the parent Streamlit page."""
    commands_json = json.dumps(command_payload(), ensure_ascii=False).replace("</", "<\\/")
    context_json = json.dumps({"currentPage": current_page, "userName": user_name}, ensure_ascii=False).replace("</", "<\\/")

    components.html(
        f"""
        <script>
        (() => {{
          const parentDoc = window.parent.document;
          const parentWin = window.parent;
          const COMMANDS = {commands_json};
          const CONTEXT = {context_json};
          const ROOT_ID = 'cadivor-command-center-v341';
          const STYLE_ID = 'cadivor-command-center-style-v341';
          const RECENT_KEY = 'cadivor-command-center-recent-v1';

          const oldRoot = parentDoc.getElementById(ROOT_ID);
          if (oldRoot) oldRoot.remove();
          const oldStyle = parentDoc.getElementById(STYLE_ID);
          if (oldStyle) oldStyle.remove();

          const style = parentDoc.createElement('style');
          style.id = STYLE_ID;
          style.textContent = `
            #${{ROOT_ID}} {{ position:fixed; inset:0; z-index:2147483000; display:none; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
            #${{ROOT_ID}}.open {{ display:block; }}
            #${{ROOT_ID}} .cvcc-backdrop {{ position:absolute; inset:0; background:rgba(15,23,42,.42); backdrop-filter:blur(7px); -webkit-backdrop-filter:blur(7px); }}
            #${{ROOT_ID}} .cvcc-panel {{ position:relative; width:min(720px,calc(100vw - 32px)); max-height:min(680px,calc(100vh - 80px)); margin:9vh auto 0; overflow:hidden; border:1px solid rgba(203,213,225,.95); border-radius:22px; background:#fff; box-shadow:0 34px 90px rgba(15,23,42,.28); animation:cvcc-in .14s ease-out; }}
            @keyframes cvcc-in {{ from {{ opacity:0; transform:translateY(-8px) scale(.985); }} to {{ opacity:1; transform:none; }} }}
            #${{ROOT_ID}} .cvcc-header {{ padding:18px 20px 14px; border-bottom:1px solid #e8edf4; }}
            #${{ROOT_ID}} .cvcc-brand-row {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }}
            #${{ROOT_ID}} .cvcc-brand {{ display:flex; align-items:center; gap:10px; color:#0f172a; font-size:13px; font-weight:900; letter-spacing:-.01em; }}
            #${{ROOT_ID}} .cvcc-mark {{ width:28px; height:28px; display:grid; place-items:center; border-radius:9px; background:#2563eb; color:white; font-size:13px; font-weight:950; box-shadow:0 8px 18px rgba(37,99,235,.22); }}
            #${{ROOT_ID}} .cvcc-context {{ color:#64748b; font-size:11px; font-weight:750; }}
            #${{ROOT_ID}} .cvcc-search-wrap {{ display:flex; align-items:center; gap:11px; padding:0 14px; min-height:52px; border:1px solid #cbd5e1; border-radius:14px; background:#f8fafc; box-shadow:0 0 0 3px rgba(37,99,235,.05); }}
            #${{ROOT_ID}} .cvcc-search-icon {{ color:#2563eb; font-size:19px; }}
            #${{ROOT_ID}} input {{ flex:1; min-width:0; border:0; outline:0; background:transparent; color:#0f172a; font:700 15px/1.4 inherit; }}
            #${{ROOT_ID}} input::placeholder {{ color:#94a3b8; font-weight:650; }}
            #${{ROOT_ID}} kbd {{ padding:3px 7px; border:1px solid #dbe3ee; border-bottom-width:2px; border-radius:7px; background:#fff; color:#64748b; font:800 10px/1.2 inherit; white-space:nowrap; }}
            #${{ROOT_ID}} .cvcc-body {{ max-height:490px; overflow:auto; padding:10px; scrollbar-width:thin; }}
            #${{ROOT_ID}} .cvcc-empty-intel {{ padding:12px 10px 8px; }}
            #${{ROOT_ID}} .cvcc-greeting {{ color:#0f172a; font-size:18px; font-weight:950; letter-spacing:-.025em; }}
            #${{ROOT_ID}} .cvcc-intro {{ margin-top:4px; color:#64748b; font-size:12px; font-weight:650; }}
            #${{ROOT_ID}} .cvcc-section-title {{ padding:13px 10px 6px; color:#94a3b8; font-size:10px; font-weight:950; letter-spacing:.09em; text-transform:uppercase; }}
            #${{ROOT_ID}} .cvcc-item {{ width:100%; display:grid; grid-template-columns:38px minmax(0,1fr) auto; align-items:center; gap:11px; padding:10px; border:0; border-radius:12px; background:transparent; text-align:left; cursor:pointer; }}
            #${{ROOT_ID}} .cvcc-item:hover,#${{ROOT_ID}} .cvcc-item.active {{ background:#eff6ff; }}
            #${{ROOT_ID}} .cvcc-item.active {{ box-shadow:inset 0 0 0 1px #bfdbfe; }}
            #${{ROOT_ID}} .cvcc-icon {{ width:36px; height:36px; display:grid; place-items:center; border:1px solid #e2e8f0; border-radius:11px; background:#fff; color:#2563eb; font-size:15px; font-weight:950; }}
            #${{ROOT_ID}} .cvcc-title {{ overflow:hidden; color:#0f172a; font-size:13px; font-weight:900; text-overflow:ellipsis; white-space:nowrap; }}
            #${{ROOT_ID}} .cvcc-subtitle {{ margin-top:2px; overflow:hidden; color:#64748b; font-size:11px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }}
            #${{ROOT_ID}} .cvcc-shortcut {{ color:#94a3b8; font-size:10px; font-weight:800; }}
            #${{ROOT_ID}} .cvcc-no-results {{ padding:38px 20px; text-align:center; color:#64748b; font-size:13px; font-weight:700; }}
            #${{ROOT_ID}} .cvcc-footer {{ display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 16px; border-top:1px solid #e8edf4; background:#f8fafc; color:#64748b; font-size:10px; font-weight:750; }}
            #${{ROOT_ID}} .cvcc-footer span {{ display:flex; align-items:center; gap:5px; }}
            .cadivor-search-pill {{ cursor:pointer!important; }}
            @media(max-width:640px) {{ #${{ROOT_ID}} .cvcc-panel {{ margin-top:4vh; max-height:92vh; }} #${{ROOT_ID}} .cvcc-context,#${{ROOT_ID}} .cvcc-shortcut {{ display:none; }} }}
          `;
          parentDoc.head.appendChild(style);

          const root = parentDoc.createElement('div');
          root.id = ROOT_ID;
          root.innerHTML = `
            <div class="cvcc-backdrop"></div>
            <section class="cvcc-panel" role="dialog" aria-modal="true" aria-label="Engineering Intelligence Command Center">
              <header class="cvcc-header">
                <div class="cvcc-brand-row"><div class="cvcc-brand"><span class="cvcc-mark">C</span>Engineering Intelligence</div><div class="cvcc-context">${{CONTEXT.currentPage}}</div></div>
                <div class="cvcc-search-wrap"><span class="cvcc-search-icon">⌕</span><input aria-label="Search Cadivor" autocomplete="off" placeholder="Search pages, actions, reports, or engineering workflows…"><kbd>ESC</kbd></div>
              </header>
              <main class="cvcc-body"></main>
              <footer class="cvcc-footer"><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>↵</kbd> Open</span><span>Cadivor Command Center · 34.1</span></footer>
            </section>`;
          parentDoc.body.appendChild(root);

          const input = root.querySelector('input');
          const body = root.querySelector('.cvcc-body');
          let visible = [];
          let activeIndex = 0;

          const normalized = value => (value || '').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
          const score = (command, query) => {{
            const q = normalized(query);
            if (!q) return 1;
            const title = normalized(command.title);
            const haystack = normalized([command.title, command.subtitle, command.category, ...(command.keywords || [])].join(' '));
            if (title === q) return 120;
            if (title.startsWith(q)) return 95;
            if (title.includes(q)) return 75;
            const terms = q.split(' ');
            if (terms.every(term => haystack.includes(term))) return 55 + terms.length;
            let cursor = 0;
            for (const char of q.replace(/ /g,'')) {{ cursor = haystack.indexOf(char, cursor); if (cursor < 0) return 0; cursor += 1; }}
            return 20;
          }};
          const recentIds = () => {{ try {{ return JSON.parse(parentWin.localStorage.getItem(RECENT_KEY) || '[]'); }} catch (_) {{ return []; }} }};
          const remember = id => {{ const next = [id, ...recentIds().filter(item => item !== id)].slice(0,6); parentWin.localStorage.setItem(RECENT_KEY, JSON.stringify(next)); }};
          const navigate = command => {{ remember(command.id); close(); parentWin.location.href = command.href; }};
          const itemHtml = (command, index) => `<button class="cvcc-item ${{index === activeIndex ? 'active' : ''}}" data-index="${{index}}"><span class="cvcc-icon">${{command.icon}}</span><span><div class="cvcc-title">${{command.title}}</div><div class="cvcc-subtitle">${{command.subtitle}}</div></span><span class="cvcc-shortcut">${{command.shortcut || command.category}}</span></button>`;

          const render = () => {{
            const query = input.value.trim();
            const ranked = COMMANDS.map(command => ({{ command, score: score(command, query) }})).filter(row => row.score > 0).sort((a,b) => b.score-a.score || a.command.title.localeCompare(b.command.title));
            visible = ranked.map(row => row.command).slice(0,14);
            activeIndex = Math.max(0, Math.min(activeIndex, visible.length - 1));
            if (!query) {{
              const recents = recentIds().map(id => COMMANDS.find(command => command.id === id)).filter(Boolean);
              const recommended = COMMANDS.filter(command => ['bom-analyzer','monitoring','alternative-finder','reports','decisions'].includes(command.id));
              visible = [...recents, ...recommended.filter(command => !recents.some(item => item.id === command.id))].slice(0,10);
              body.innerHTML = `<div class="cvcc-empty-intel"><div class="cvcc-greeting">Good ${{new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'}}, ${{CONTEXT.userName}}.</div><div class="cvcc-intro">Where should Cadivor take you next?</div></div><div class="cvcc-section-title">${{recents.length ? 'Recent and recommended' : 'Recommended actions'}}</div>${{visible.map(itemHtml).join('')}}`;
            }} else if (visible.length) {{
              const grouped = [];
              visible.forEach(command => {{ let group = grouped.find(item => item.name === command.category); if (!group) {{ group = {{name:command.category, commands:[]}}; grouped.push(group); }} group.commands.push(command); }});
              let running = 0;
              body.innerHTML = grouped.map(group => `<div class="cvcc-section-title">${{group.name}}</div>${{group.commands.map(command => itemHtml(command, running++)).join('')}}`).join('');
            }} else {{ body.innerHTML = `<div class="cvcc-no-results">No command found for “${{query.replace(/[<>]/g,'')}}”.<br>Try a page, workflow, report, supplier, or component action.</div>`; }}
            body.querySelectorAll('.cvcc-item').forEach(button => button.addEventListener('click', () => navigate(visible[Number(button.dataset.index)])));
            body.querySelector('.cvcc-item.active')?.scrollIntoView({{block:'nearest'}});
          }};
          const open = () => {{ root.classList.add('open'); input.value=''; activeIndex=0; render(); setTimeout(() => input.focus(), 20); }};
          const close = () => {{ root.classList.remove('open'); }};

          root.querySelector('.cvcc-backdrop').addEventListener('click', close);
          input.addEventListener('input', () => {{ activeIndex=0; render(); }});
          root.addEventListener('keydown', event => {{
            if (event.key === 'Escape') {{ event.preventDefault(); close(); }}
            if (event.key === 'ArrowDown') {{ event.preventDefault(); activeIndex = visible.length ? (activeIndex+1)%visible.length : 0; render(); }}
            if (event.key === 'ArrowUp') {{ event.preventDefault(); activeIndex = visible.length ? (activeIndex-1+visible.length)%visible.length : 0; render(); }}
            if (event.key === 'Enter' && visible[activeIndex]) {{ event.preventDefault(); navigate(visible[activeIndex]); }}
          }});

          if (parentWin.__cadivorCommandKeyHandler) parentDoc.removeEventListener('keydown', parentWin.__cadivorCommandKeyHandler, true);
          parentWin.__cadivorCommandKeyHandler = event => {{
            const target = event.target;
            const editable = target && (target.matches?.('input,textarea,select') || target.isContentEditable);
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {{ event.preventDefault(); event.stopPropagation(); open(); }}
            else if (!editable && event.key === '/' && !root.classList.contains('open')) {{ event.preventDefault(); open(); }}
          }};
          parentDoc.addEventListener('keydown', parentWin.__cadivorCommandKeyHandler, true);

          parentDoc.querySelectorAll('.cadivor-search-pill').forEach(trigger => {{
            trigger.setAttribute('href','#');
            trigger.innerHTML = 'Search Cadivor <span style="margin-left:12px;color:#94a3b8;font-size:10px;font-weight:900">⌘K</span>';
            trigger.onclick = event => {{ event.preventDefault(); open(); }};
          }});
          parentWin.openCadivorCommandCenter = open;
        }})();
        </script>
        """,
        height=0,
        width=0,
    )

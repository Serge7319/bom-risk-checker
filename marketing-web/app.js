(() => {
  const APP_URL = window.CADIVOR_APP_URL || 'https://app.cadivor.com';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MOTION = { fast: 180, standard: 520, slow: 650, steps: 14, tick: 32, hover: 220 };
  /** Hero + workflow auto-play; other homepage sections stay static until replay. */
  const HOME_SECTION_AUTOPLAY = true;

  const homeCleanup = [];
  function registerHomeCleanup(fn) {
    homeCleanup.push(fn);
  }
  function cleanupHomePage() {
    while (homeCleanup.length) {
      try { homeCleanup.pop()?.(); } catch (err) { console.error('Home cleanup failed:', err); }
    }
    launchAudit.markCleanup();
  }

  const launchAudit = (() => {
    const enabled = /cadivor_audit=1/i.test(`${location.search}${location.hash}`);
    const results = {
      commandCycles: 0,
      copilotCycles: 0,
      workflowCycles: 0,
      supplierFullPasses: 0,
      commandStagesSeen: [],
      supplierSeen: [],
      errors: [],
      cleanupCount: 0,
      homeInitCount: 0
    };
    let lastAutoSupplier = null;
    const supplierOrder = ['DigiKey', 'Mouser', 'Newark'];

    function assert(ok, msg) {
      if (!ok) results.errors.push(msg);
    }

    function onHomeInit() {
      results.homeInitCount++;
    }

    function markCleanup() {
      results.cleanupCount++;
    }

    function onCommandStep(step) {
      const s = commandStates?.[step];
      if (!s) return;
      results.commandStagesSeen.push(`${s.health}/${s.blockers}/${s.alerts}/${s.decisions}`);
    }

    function onCommandCycleComplete() {
      results.commandCycles++;
    }

    function onCopilotCycleComplete() {
      results.copilotCycles++;
    }

    function onWorkflowCycleComplete() {
      results.workflowCycles++;
    }

    function onSupplierSelect(index, fromUser) {
      const name = supplierOrder[index];
      if (!name) return;
      results.supplierSeen.push(name);
      if (!fromUser && lastAutoSupplier === 'Newark' && name === 'DigiKey') results.supplierFullPasses++;
      if (!fromUser) lastAutoSupplier = name;
    }

    function finalize() {
      window.__cadivorLaunchAudit = { ...results, ts: Date.now() };
      if (enabled && results.errors.length) console.warn('[Cadivor audit]', results.errors);
    }

    return {
      enabled,
      results,
      assert,
      onHomeInit,
      markCleanup,
      onCommandStep,
      onCommandCycleComplete,
      onCopilotCycleComplete,
      onWorkflowCycleComplete,
      onSupplierSelect,
      finalize
    };
  })();

  function createVisibleLoop({
    element,
    play,
    reset,
    finalHold = 8000,
    restartDelay = 500,
    threshold = 0.4,
    pauseOnHover = true,
    pauseOnFocus = false,
    autoplay = true,
    onReplayReady,
    showFinal,
    showIdle
  }) {
    const state = { isVisible: false, isPlaying: false, isPaused: false, timerIds: [], runToken: 0 };
    let tabHidden = document.hidden;
    let hasStarted = false;
    let observer = null;
    const teardown = [];

    function clearTimers() {
      state.timerIds.forEach(id => clearTimeout(id));
      state.timerIds = [];
    }

    function isActive(token) {
      return token === state.runToken && state.isVisible && !state.isPaused && !tabHidden;
    }

    function schedule(fn, delay, token) {
      const id = setTimeout(() => {
        state.timerIds = state.timerIds.filter(x => x !== id);
        if (token !== undefined && token !== state.runToken) return;
        if (state.isPaused || tabHidden) {
          schedule(fn, Math.min(Math.max(delay, 120), 280), token);
          return;
        }
        fn();
      }, reducedMotion ? 0 : delay);
      state.timerIds.push(id);
      return id;
    }

    function bumpToken() {
      state.runToken++;
      clearTimers();
      return state.runToken;
    }

    function setReplayDisabled(disabled) {
      onReplayReady?.(disabled, hasStarted);
    }

    function stopCycle() {
      bumpToken();
      state.isPlaying = false;
      setReplayDisabled(false);
    }

    function beginCycle() {
      if (reducedMotion) {
        showFinal?.();
        hasStarted = true;
        setReplayDisabled(false);
        return;
      }
      if (!state.isVisible || state.isPaused || tabHidden || state.isPlaying) return;

      const token = bumpToken();
      state.isPlaying = true;
      hasStarted = true;
      setReplayDisabled(true);

      const ctx = {
        token,
        schedule: (fn, delay) => schedule(fn, delay, token),
        isActive: () => isActive(token),
        complete: () => {
          if (token !== state.runToken) return;
          state.isPlaying = false;
          setReplayDisabled(false);
          if (!state.isVisible || reducedMotion) return;
          schedule(() => {
            if (!isActive(token)) return;
            reset?.({ soft: true, schedule: ctx.schedule, isActive: ctx.isActive, token });
            schedule(() => {
              if (state.isVisible && !state.isPaused && !tabHidden) beginCycle();
            }, restartDelay, token);
          }, finalHold, token);
        },
        abort: () => {
          if (token !== state.runToken) return;
          state.isPlaying = false;
          setReplayDisabled(false);
        }
      };

      play(ctx);
    }

    function requestReplay() {
      stopCycle();
      reset?.({ soft: false });
      schedule(() => beginCycle(), restartDelay);
    }

    function onTabVisibility() {
      tabHidden = document.hidden;
      if (tabHidden) clearTimers();
      else if (autoplay && state.isVisible && !state.isPlaying && !reducedMotion) beginCycle();
    }

    observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        state.isVisible = entry.isIntersecting;
        if (entry.isIntersecting) {
          if (!autoplay) {
            if (!hasStarted) {
              showIdle?.();
              hasStarted = true;
              setReplayDisabled(false);
            }
            return;
          }
          if (!state.isPlaying && !reducedMotion) beginCycle();
        } else {
          stopCycle();
          if (!autoplay) hasStarted = false;
        }
      });
    }, { threshold });

    if (element) observer.observe(element);

    document.addEventListener('visibilitychange', onTabVisibility);
    teardown.push(() => document.removeEventListener('visibilitychange', onTabVisibility));

    if (element && pauseOnHover) {
      const pause = () => { state.isPaused = true; };
      const resume = () => {
        state.isPaused = false;
        if (autoplay && state.isVisible && !state.isPlaying && !reducedMotion) beginCycle();
      };
      element.addEventListener('mouseenter', pause);
      element.addEventListener('mouseleave', resume);
      teardown.push(() => {
        element.removeEventListener('mouseenter', pause);
        element.removeEventListener('mouseleave', resume);
      });
    }

    if (element && pauseOnFocus) {
      const pause = () => { state.isPaused = true; };
      const resume = (e) => {
        if (element.contains(e.relatedTarget)) return;
        state.isPaused = false;
        if (autoplay && state.isVisible && !state.isPlaying && !reducedMotion) beginCycle();
      };
      element.addEventListener('focusin', pause);
      element.addEventListener('focusout', resume);
      teardown.push(() => {
        element.removeEventListener('focusin', pause);
        element.removeEventListener('focusout', resume);
      });
    }

    function destroy() {
      stopCycle();
      observer?.disconnect();
      teardown.forEach(fn => fn());
    }

    if (reducedMotion) showFinal?.();
    else if (!autoplay) onReplayReady?.(false, true);

    return { state, requestReplay, destroy, beginCycle };
  }

  function setReplayButton(btn, disabled, show) {
    if (!btn) return;
    btn.disabled = !!disabled;
    if (show) btn.removeAttribute('hidden');
    else if (reducedMotion) btn.setAttribute('hidden', '');
  }

  document.querySelectorAll('.app-link').forEach(a => {
    a.href = `${APP_URL}?auth=${encodeURIComponent(a.dataset.auth || 'login')}`;
  });

  const validPages = ['home', 'product', 'solutions', 'pricing', 'resources', 'company', 'contact', 'security', 'privacy', 'terms'];
  function route() {
    let page = (location.hash.match(/^#\/([^?#]+)/) || [])[1] || 'home';
    if (!validPages.includes(page)) page = 'home';
    $$('.page').forEach(p => p.classList.toggle('active', p.dataset.page === page));
    $$('.site-header nav a').forEach(a => a.classList.toggle('active', a.getAttribute('href') === `#/${page}`));
    document.title = `${page === 'home' ? 'Cadivor' : page[0].toUpperCase() + page.slice(1) + ' — Cadivor'}`;
    $('#mainNav')?.classList.remove('open');
    window.scrollTo(0, 0);
    syncHomeMode();
    refreshGlobalMotion();
    const anchor = (location.hash.match(/#\/[^#]+#([^?#]+)/) || [])[1];
    if (anchor) {
      requestAnimationFrame(() => {
        document.getElementById(anchor)?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
      });
    }
  }
  addEventListener('hashchange', route);
  $('#menuToggle')?.addEventListener('click', () => $('#mainNav')?.classList.toggle('open'));
  $$('[data-home-anchor]').forEach(a => a.addEventListener('click', e => {
    e.preventDefault();
    const id = a.dataset.homeAnchor;
    if (!$('.page[data-page="home"]')?.classList.contains('active')) {
      location.hash = '#/home';
      setTimeout(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' }), 80);
    } else document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  }));

  const q = 'Is this BOM ready for production release?';
  const ansShort = 'No. Two issues currently block release.';
  const ansDetails = [
    'MPU6050 lifecycle exposure',
    'LM35DN single-source concentration'
  ];
  const ansFull = 'No. Two issues currently block release. Qualify the LM35DN second source and replace the MPU6050 before approval.';
  const VALIDATION_LINES = [
    'Validating columns…',
    'Checking 1,842 rows…',
    'Matching manufacturer part numbers…',
    'File validation progress'
  ];

  const REVIEW = [
    { key: 'received', label: 'BOM received', focus: 'upload', duration: 700 },
    { key: 'validating', label: 'Validating BOM', focus: 'upload', duration: 1100 },
    { key: 'analyzing', label: 'Analyzing release posture', focus: 'analyze', duration: 900 },
    { key: 'risks-found', label: 'Release blockers identified', focus: 'analyze', duration: 1000 },
    { key: 'copilot-question', label: 'Engineer asks Cadivor', focus: 'copilot', duration: 1500 },
    { key: 'evidence-review', label: 'Evidence review', focus: 'copilot', duration: 1800 },
    { key: 'recommendation', label: 'Recommendation ready', focus: 'copilot', duration: 1500 },
    { key: 'supplier-qualification', label: 'Supplier qualification', focus: 'supplier', duration: 1100 },
    { key: 'decision-ready', label: 'Decision ready', focus: 'decision', duration: 1300 },
    { key: 'approved', label: 'Decision approved', focus: 'decision', duration: 1300 },
    { key: 'monitoring-active', label: 'Monitoring active', focus: 'monitor', duration: 2200 }
  ];
  const heroMetrics = [
    null, null,
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 },
    { health: 72, blockers: 4, alerts: 17, alternates: 3 }
  ];
  const phaseWidths = [4, 12, 28, 42, 52, 62, 72, 80, 88, 94, 100];
  const commandStates = [
    { phase: 'Baseline risk posture', health: 72, blockers: 4, alerts: 17, decisions: 16, ring: 'Blocked', headline: 'Release blocked by component risks', detail: 'Cadivor is tracing lifecycle and supplier evidence before recommending action.', statuses: ['Blocker', 'Open', 'Review'] },
    { phase: 'Alternate identified', health: 81, blockers: 2, alerts: 12, decisions: 16, ring: 'Mitigation in progress', headline: 'MPU6050 alternate identified', detail: 'ICM-42688-P reduces confirmed EOL exposure while preserving electrical compatibility.', statuses: ['Resolved', 'Qualifying', 'Review'] },
    { phase: 'Second source qualified', health: 89, blockers: 1, alerts: 8, decisions: 17, ring: 'Final qualification', headline: 'LM35DN second source qualified', detail: 'DigiKey provides the strongest authorized inventory and verified lead-time posture.', statuses: ['Resolved', 'Qualified', 'Review'] },
    { phase: 'Release posture resolved', health: 96, blockers: 0, alerts: 5, decisions: 18, ring: 'Ready for controlled production release', headline: 'Ready for controlled production release', detail: 'Cadivor linked 14 evidence points to DR-1048 and activated monitoring.', statuses: ['Resolved', 'Qualified', 'Monitoring'] }
  ];
  const WF_STEPS = [
    { state: 'Validated', outcomeHtml: 'Validated · <b>1,842</b> components', detail: 'motor_controller_rev_c.xlsx · 36 suppliers normalized', duration: 1200 },
    { state: 'Scored', outcomeHtml: 'BOM Health <b>72</b> · <b>4</b> blockers', detail: 'MPU6050 EOL · LM35DN lead time · lifecycle notices matched', duration: 1300 },
    { state: 'Reviewing', outcomeHtml: '<b>14</b> evidence points reviewed', detail: 'Lifecycle, supply, alternates, and prior decisions assembled', duration: 1300 },
    { state: 'Approved', outcomeHtml: '<b>DR-1048</b> approved', detail: 'Owner Jordan Ellis · evidence hash verified', duration: 1300 },
    { state: 'Active', outcomeHtml: 'Lifecycle and supply monitoring active', detail: 'Watching MPU6050 · LM35DN · TPS54331 across authorized sources', duration: 0 }
  ];

  let reviewStage = 0;
  let reviewTimer = null;
  let reviewAuto = true;
  let theaterHoverPause = false;
  let theaterFocusPause = false;
  let theaterTabHidden = false;
  let typing = [];
  let answerStream = null;
  let heroTimers = [];
  let heroScrollToken = 0;

  function clearTyping() { typing.forEach(clearTimeout); typing = []; }
  function clearAnswerStream() { if (answerStream) { clearInterval(answerStream); answerStream = null; } }
  function clearHeroTimers() { heroTimers.forEach(clearTimeout); heroTimers = []; }

  function scrollTheaterTo(target, options = {}) {
    const viewport = $('#heroTheaterViewport');
    const element = typeof target === 'string' ? $(target) : target;
    if (!viewport || !element) return;
    heroScrollToken++;
    const viewportRect = viewport.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();
    const targetTop = viewport.scrollTop + elementRect.top - viewportRect.top - (options.offset ?? 24);
    viewport.scrollTo({
      top: Math.max(0, targetTop),
      behavior: reducedMotion ? 'auto' : 'smooth'
    });
  }

  function resetTheaterViewport(smooth = true) {
    const viewport = $('#heroTheaterViewport');
    if (!viewport) return;
    heroScrollToken++;
    viewport.scrollTo({ top: 0, behavior: smooth && !reducedMotion ? 'smooth' : 'auto' });
  }

  const HERO_SCROLL_TARGETS = [
    ['#uploadCard', { offset: 12 }],
    ['#uploadCard', { offset: 12 }],
    ['#demo-metrics', { offset: 16 }],
    ['#riskList', { offset: 16 }],
    ['#chatQuestion', { offset: 20 }],
    ['#reasoningSteps', { offset: 20 }],
    ['#chatAi', { offset: 16 }],
    ['#supplierPanel', { offset: 16 }],
    ['#decisionPanel', { offset: 12 }],
    ['#heroDecisionApprove', { offset: 28 }],
    ['#heroMonitorPanel', { offset: 16 }]
  ];

  function scheduleHeroViewportScroll(i) {
    const spec = HERO_SCROLL_TARGETS[i];
    if (!spec) return;
    heroTimers.push(setTimeout(() => scrollTheaterTo(spec[0], spec[1]), reducedMotion ? 0 : 140));
  }

  function type(node, text, speed, delay = 0) {
    if (!node) return;
    node.textContent = '';
    if (reducedMotion) { node.textContent = text; return; }
    [...text].forEach((c, i) => typing.push(setTimeout(() => { node.textContent += c; }, delay + i * speed)));
  }

  function streamText(node, text, speed = 20, onDone) {
    if (!node) return;
    clearAnswerStream();
    if (reducedMotion) { node.textContent = text; onDone?.(); return; }
    node.textContent = '';
    let i = 0;
    answerStream = setInterval(() => {
      if (i >= text.length) { clearAnswerStream(); onDone?.(); return; }
      node.textContent += text[i++];
    }, speed);
  }

  function streamChunks(node, chunks, gap = 280, onDone) {
    if (!node) return;
    clearAnswerStream();
    if (reducedMotion) {
      node.textContent = chunks.join(' ');
      onDone?.();
      return;
    }
    node.textContent = '';
    let ci = 0;
    const addChunk = () => {
      if (ci >= chunks.length) { onDone?.(); return; }
      node.textContent += (ci ? ' ' : '') + chunks[ci++];
      heroTimers.push(setTimeout(addChunk, gap));
    };
    addChunk();
  }

  function animateNumber(el, value, suffix = '') {
    if (!el || value == null) return;
    const raw = String(el.textContent);
    const current = raw === '—' || raw === '0' ? 0 : parseInt(raw.replace(/[^\d-]/g, ''), 10) || 0;
    const display = (n) => { el.textContent = `${n}${suffix}`; };
    if (current === value) { display(value); return; }
    if (reducedMotion) { display(value); return; }
    let step = 0;
    const diff = value - current;
    const tick = setInterval(() => {
      step++;
      display(Math.round(current + (diff * step / MOTION.steps)));
      if (step >= MOTION.steps) {
        clearInterval(tick);
        display(value);
      }
    }, MOTION.tick);
  }

  function animateKpiElement(el) {
    if (!el || el.dataset.kpiAnimated === '1') return;
    const target = Number(el.dataset.kpiCounter);
    if (!Number.isFinite(target)) return;
    el.dataset.kpiAnimated = '1';
    const suffix = el.dataset.kpiSuffix || '';
    if (reducedMotion) {
      el.textContent = `${target}${suffix}`;
      return;
    }
    el.textContent = `0${suffix}`;
    animateNumber(el, target, suffix);
  }

  function resetKpiElement(el) {
    if (!el || !el.dataset.kpiCounter) return;
    delete el.dataset.kpiAnimated;
    el.textContent = `0${el.dataset.kpiSuffix || ''}`;
  }

  function animateMetricText(el) {
    if (!el) return;
    const text = el.dataset.fullText || el.textContent;
    const match = text.match(/([\d,]+)/);
    if (!match) return;
    if (!el.dataset.fullText) el.dataset.fullText = text;
    if (reducedMotion) return;
    const target = parseInt(match[1].replace(/,/g, ''), 10);
    const prefix = text.slice(0, match.index);
    const suffix = text.slice(match.index + match[1].length);
    let step = 0;
    const tick = setInterval(() => {
      step++;
      const val = Math.round((target * step) / MOTION.steps);
      el.textContent = `${prefix}${val.toLocaleString()}${suffix}`;
      if (step >= MOTION.steps) {
        clearInterval(tick);
        el.textContent = text;
      }
    }, MOTION.tick);
  }

  function initKpiCards() {
    const kpiRoots = $$('[data-kpi-section], .launch-proof, .company-stats');
    const seen = new WeakSet();

    function bindSection(section) {
      if (!section || seen.has(section)) return;
      if (!HOME_SECTION_AUTOPLAY && section.classList.contains('launch-proof')) return;
      seen.add(section);
      const counters = $$('[data-kpi-counter]', section);
      if (!counters.length) return;

      const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            counters.forEach((el, i) => {
              if (reducedMotion) animateKpiElement(el);
              else setTimeout(() => animateKpiElement(el), i * 90);
            });
          } else {
            counters.forEach(resetKpiElement);
          }
        });
      }, { threshold: 0.35 });

      observer.observe(section);
    }

    kpiRoots.forEach(bindSection);
    $$('.page.active [data-kpi-counter]').forEach(el => {
      const section = el.closest('.launch-proof, .company-stats, .resource-showcase, .report-stack') || el.closest('section, .page-hero');
      if (section) bindSection(section);
    });
  }

  let motionObserver = null;
  const motionSeen = new WeakSet();

  function applyMotionDelays(root = document) {
    $$('[data-motion-delay]', root).forEach(el => {
      el.style.setProperty('--motion-delay', `${el.dataset.motionDelay}ms`);
    });
  }

  function observeMotionElements(root = document) {
    applyMotionDelays(root);
    if (reducedMotion) {
      $$('[data-motion="reveal"]', root).forEach(el => el.classList.add('motion-visible'));
      return;
    }
    if (!motionObserver) {
      motionObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          entry.target.classList.toggle('motion-visible', entry.isIntersecting);
        });
      }, { threshold: 0.14, rootMargin: '0px 0px -6% 0px' });
    }
    const page = $('.page.active');
    if (page) {
      ['.page-hero', '.product-module', '.solution-scene', '.pricing-grid > article', '.resource-showcase', '.company-story', '.company-stats article', '.inner-cta'].forEach(sel => {
        $$(sel, page).forEach(el => {
          if (!el.dataset.motion) el.dataset.motion = 'reveal';
        });
      });
    }
    const scope = page || root;
    $$('[data-motion="reveal"]', scope).forEach(el => {
      if (motionSeen.has(el)) return;
      motionSeen.add(el);
      motionObserver.observe(el);
    });
  }

  function refreshGlobalMotion() {
    observeMotionElements();
  }

  function applyHeroMetrics(i, stagger = false) {
    const m = heroMetrics[i];
    if (!m) {
      ['#healthValue', '#blockerValue', '#alertValue', '#alternateValue'].forEach(sel => { const el = $(sel); if (el) el.textContent = '—'; });
      return;
    }
    const apply = (sel, val, delay = 0) => {
      if (val == null) return;
      if (stagger && !reducedMotion) heroTimers.push(setTimeout(() => animateNumber($(sel), val), delay));
      else animateNumber($(sel), val);
    };
    apply('#healthValue', m.health, 0);
    apply('#blockerValue', m.blockers, stagger ? 220 : 0);
    apply('#alertValue', m.alerts, stagger ? 440 : 0);
    apply('#alternateValue', m.alternates, stagger ? 660 : 0);
  }

  function moveCursor(cursor, host, target, click = false) {
    if (!cursor || !host || !target) return;
    const h = host.getBoundingClientRect();
    const t = target.getBoundingClientRect();
    const x = t.left - h.left + t.width / 2;
    const y = t.top - h.top + t.height / 2;
    cursor.style.left = `${x}px`;
    cursor.style.top = `${y}px`;
    cursor.classList.add('visible');
    target.classList.toggle('demo-target', click);
    cursor.classList.toggle('clicking', click);
    if (click) setTimeout(() => target.classList.remove('demo-target'), MOTION.standard + 60);
  }

  function hideCursor(cursor) {
    cursor?.classList.remove('visible', 'clicking');
  }

  function positionHeroFile(i) {
    const theater = $('#productTheater');
    const file = $('#floatFile');
    const upload = $('#uploadCard');
    if (!theater || !file || !upload) return;
    const tr = theater.getBoundingClientRect();
    const ur = upload.getBoundingClientRect();
    const edgeLeft = ur.left - tr.left - 68;
    const edgeTop = ur.top - tr.top - 44;
    const dropLeft = ur.left - tr.left + 14;
    const dropTop = ur.top - tr.top + 10;
    if (i === 0) {
      file.classList.add('active');
      file.classList.remove('dropped');
      file.style.left = `${edgeLeft}px`;
      file.style.top = `${edgeTop}px`;
      file.style.transform = 'rotate(-5deg)';
      if (!reducedMotion) {
        heroTimers.push(setTimeout(() => {
          file.classList.add('dropped');
          file.style.left = `${dropLeft}px`;
          file.style.top = `${dropTop}px`;
          file.style.transform = 'rotate(0deg)';
        }, MOTION.standard + 60));
      } else {
        file.classList.add('dropped');
        file.style.left = `${dropLeft}px`;
        file.style.top = `${dropTop}px`;
        file.style.transform = 'rotate(0deg)';
      }
    } else if (i === 1) {
      file.classList.add('active', 'dropped');
      file.style.left = `${dropLeft}px`;
      file.style.top = `${dropTop}px`;
      file.style.transform = 'rotate(0deg)';
    } else if (i <= 10) {
      file.classList.add('active', 'dropped');
      file.style.opacity = i >= 10 ? '0.72' : '1';
    } else {
      file.classList.remove('active', 'dropped');
    }
  }

  function animateValidationProgress() {
    const bar = $('#uploadProgress');
    if (!bar) return;
    bar.style.transform = 'scaleX(0)';
    if (reducedMotion) { bar.style.transform = 'scaleX(1)'; return; }
    let pct = 0;
    const tick = setInterval(() => {
      pct += 3;
      bar.style.transform = `scaleX(${Math.min(pct, 100) / 100})`;
      if (pct >= 100) clearInterval(tick);
    }, 45);
    heroTimers.push(setTimeout(() => clearInterval(tick), 2000));
  }

  function cycleValidationCopy() {
    const meta = $('#uploadMeta');
    if (!meta) return;
    VALIDATION_LINES.forEach((line, li) => {
      heroTimers.push(setTimeout(() => { meta.textContent = line; }, li * (reducedMotion ? 0 : 420)));
    });
  }

  function revealHeroRisks(i) {
    $$('.risk-row').forEach((row, ri) => {
      row.classList.remove('visible', 'reorder');
      if (i < 3) return;
      if (reducedMotion) row.classList.add('visible');
      else heroTimers.push(setTimeout(() => row.classList.add('visible'), ri * (reducedMotion ? 0 : 300)));
      if (i === 7 && ri === 0) row.classList.add('reorder');
    });
  }

  function revealRecommendation(i) {
    const details = $('#answerDetails');
    const chatAi = $('#chatAi');
    chatAi?.classList.add('visible', 'streaming');
    $('#confidenceLabel').textContent = '93% confidence';
    if (i !== 6) {
      $('#answerText').textContent = ansShort;
      if (details) {
        details.hidden = false;
        details.classList.add('visible');
        details.innerHTML = ansDetails.map(d => `<li>${d}</li>`).join('') + '<li class="answer-confidence">Confidence: 93%</li><li>Recommended mitigation</li>';
      }
      chatAi?.classList.remove('streaming');
      return;
    }
    if (details) { details.hidden = true; details.classList.remove('visible'); details.innerHTML = ''; }
    streamText($('#answerText'), ansShort, 22, () => {
      if (reducedMotion) {
        if (details) {
          details.hidden = false;
          details.classList.add('visible');
          details.innerHTML = ansDetails.map(d => `<li>${d}</li>`).join('') + '<li class="answer-confidence">Confidence: 93%</li><li>Recommended mitigation</li>';
        }
        chatAi?.classList.remove('streaming');
        return;
      }
      let line = 0;
      const addLine = () => {
        if (!details) return;
        details.hidden = false;
        details.classList.add('visible');
        if (line < ansDetails.length) {
          const li = document.createElement('li');
          li.textContent = ansDetails[line++];
          details.appendChild(li);
          heroTimers.push(setTimeout(addLine, 260));
        } else {
          const conf = document.createElement('li');
          conf.className = 'answer-confidence';
          conf.textContent = 'Confidence: 93%';
          details.appendChild(conf);
          const mit = document.createElement('li');
          mit.textContent = 'Recommended mitigation';
          details.appendChild(mit);
          chatAi?.classList.remove('streaming');
        }
      };
      heroTimers.push(setTimeout(addLine, 220));
    });
  }

  function updateTheaterStageRail(i) {
    $$('#theaterStageRail span').forEach((span, n) => {
      span.classList.toggle('active', n === i);
      span.classList.toggle('done', n < i);
    });
  }

  function updateHero(i) {
    const stage = REVIEW[i];
    const theater = $('#productTheater');
    if (!theater || !stage) return;
    clearTyping();
    clearAnswerStream();
    clearHeroTimers();
    theater.dataset.reviewStage = String(i);
    theater.dataset.reviewStageKey = stage.key;
    theater.dataset.focus = stage.focus;
    $('#analysisState').textContent = stage.label;
    const productStatus = $('#heroProductStatus');
    if (productStatus) {
      productStatus.textContent = stage.label;
      productStatus.classList.remove('state-warn', 'state-ok', 'state-live');
      if (i >= 3 && i <= 8) productStatus.classList.add('state-warn');
      if (i >= 9) productStatus.classList.add('state-ok');
      if (i === 10) productStatus.classList.add('state-live');
    }
    $('#heroLiveIndicator')?.classList.toggle('visible', i >= 4 && i <= 6 || i === 10);
    $('#phaseFill').style.width = `${phaseWidths[i]}%`;

    const badge = $('.demo-main>header>span');
    badge?.classList.remove('state-warn', 'state-ok', 'state-live');
    if (i >= 3 && i <= 8) badge?.classList.add('state-warn');
    if (i >= 9) badge?.classList.add('state-ok');
    if (i === 10) badge?.classList.add('state-live');

    positionHeroFile(i);
    $('#uploadCard')?.classList.toggle('imported', i >= 1);
    $('#uploadCard')?.classList.toggle('validating', i === 1);
    $('#uploadState').textContent = i === 0 ? 'Waiting' : i === 1 ? 'Validating…' : 'Imported';
    if (i === 1) {
      animateValidationProgress();
      cycleValidationCopy();
      $('#uploadProgress').style.transform = reducedMotion ? 'scaleX(1)' : 'scaleX(0)';
    } else {
      $('#uploadProgress').style.transform = `scaleX(${i === 0 ? 0 : 1})`;
    }
    $('#uploadMeta').textContent = i >= 2 ? '1,842 components · 36 suppliers' : i === 1 ? VALIDATION_LINES[0] : 'Awaiting upload · 36 suppliers';
    $('#importWorkspace')?.classList.toggle('visible', i >= 1);
    if ($('#importRowCount')) $('#importRowCount').textContent = i >= 1 ? (i === 1 ? 'Validating 1,842 rows…' : '1,842 rows mapped') : '1,842 rows mapped';
    if ($('#importColMap')) $('#importColMap').textContent = i >= 1 ? '4 required columns matched' : '4 required columns matched';

    const acts = ['#actParse', '#actLifecycle', '#actSupplier', '#actDecisions', '#actMonitor'];
    [i >= 1, i >= 2, i >= 3, i >= 5, i >= 10].forEach((on, n) => $(acts[n])?.classList.toggle('active', on));
    applyHeroMetrics(i, i === 2 || i === 3);
    revealHeroRisks(i);

    const chatQ = $('#chatQuestion');
    chatQ?.classList.remove('typing');
    if (i < 4) $('#questionText').textContent = 'Ask a production-readiness question…';
    else if (i === 4) { chatQ?.classList.add('typing'); type($('#questionText'), q, 20); }
    else $('#questionText').textContent = q;

    const reasoning = $('#reasoningSteps');
    reasoning?.classList.toggle('visible', i >= 5);
    if (i === 5) {
      $$('#reasoningSteps span').forEach(s => s.classList.remove('active', 'done'));
      $$('#reasoningSteps span').forEach((s, si) => {
        heroTimers.push(setTimeout(() => {
          $$('#reasoningSteps span').forEach((x, xi) => {
            x.classList.toggle('active', xi === si);
            x.classList.toggle('done', xi < si);
          });
        }, si * (reducedMotion ? 0 : 340)));
      });
    } else if (i > 5) $$('#reasoningSteps span').forEach(s => { s.classList.remove('active'); s.classList.add('done'); });
    else $$('#reasoningSteps span').forEach(s => s.classList.remove('active', 'done'));

    const chatAi = $('#chatAi');
    if (i >= 6) revealRecommendation(i);
    else {
      chatAi?.classList.remove('visible', 'streaming');
      $('#answerText').textContent = '';
      const details = $('#answerDetails');
      if (details) { details.hidden = true; details.classList.remove('visible'); details.innerHTML = ''; }
    }

    $('#chatEvidence')?.classList.toggle('visible', i >= 6);
    $$('.evidence-chip').forEach((chip, ci) => {
      chip.classList.remove('visible');
      if (i >= 6) {
        if (reducedMotion) chip.classList.add('visible');
        else heroTimers.push(setTimeout(() => chip.classList.add('visible'), ci * 220));
      }
    });
    $('#confidenceLabel').textContent = i >= 6 ? '93% confidence' : i === 5 ? 'Reasoning…' : 'Evidence grounded';

    $('#decisionActions')?.classList.toggle('visible', i >= 8);
    const approveBtn = $('#demoApproveMitigation');
    approveBtn && (approveBtn.disabled = i < 9);
    approveBtn?.classList.toggle('ready', i >= 9);
    $('#decisionRef').textContent = i >= 9 ? 'DR-1048 approved' : 'DR-1048 pending';

    $('#approvalToast')?.classList.toggle('visible', i >= 10);
    $('#lifeEvidence').textContent = i >= 3 ? 'EOL notice matched' : i >= 1 ? 'Scanning…' : 'Waiting';
    $('#supplyEvidence').textContent = i >= 7 ? 'DigiKey · 42,860 units' : i >= 3 ? 'Analyzing…' : 'Waiting';
    $('#decisionEvidence').textContent = i >= 9 ? 'DR-1048 approved' : i >= 6 ? 'Draft ready' : 'Pending';

    $$('.supplier-row').forEach((row, si) => {
      row.classList.toggle('selected', si === 0 && i >= 7);
      row.classList.toggle('highlight', i === 7 && si === 0);
    });
    $('#supplierPanel')?.classList.toggle('is-active', i >= 7);
    $('#heroMonitorPanel')?.classList.toggle('is-active', i >= 10);
    $('#heroMonitorConfirm')?.classList.toggle('visible', i >= 10);

    $$('.window-layout aside button').forEach(btn => {
      btn.classList.toggle('nav-active',
        (i >= 4 && i <= 6 && btn.id === 'demoAskCadivor') ||
        (i >= 8 && i <= 9 && btn.dataset.nav === 'decisions') ||
        (i >= 10 && btn.dataset.nav === 'monitor') ||
        (i < 4 && btn.dataset.nav === 'overview'));
    });

    const heroApprove = $('#heroDecisionApprove');
    $('#decisionPanel')?.classList.toggle('approved', i >= 9);
    $('#decisionPanel')?.classList.toggle('is-active', i >= 8);
    if (heroApprove) {
      heroApprove.disabled = i < 9;
      heroApprove.classList.toggle('ready', i >= 9);
      heroApprove.textContent = i >= 9 ? '✓ Decision approved' : 'Approve decision';
    }
    if ($('#heroDecisionStatus')) $('#heroDecisionStatus').textContent = i >= 9 ? 'Decision approved' : 'Awaiting approval';

    const cursor = $('#demoCursor');
    hideCursor(cursor);
    $$('#demoAskCadivor, #demoApproveMitigation, #heroDecisionApprove').forEach(el => el?.classList.remove('demo-target'));
    if (i === 4 && cursor && !reducedMotion) {
      heroTimers.push(setTimeout(() => moveCursor(cursor, theater, $('#chatQuestion'), false), 600));
      heroTimers.push(setTimeout(() => moveCursor(cursor, theater, $('#chatQuestion'), true), 1700));
    }
    if (i === 9 && cursor && !reducedMotion) {
      heroTimers.push(setTimeout(() => scrollTheaterTo('#heroDecisionApprove', { offset: 28 }), 200));
      heroTimers.push(setTimeout(() => moveCursor(cursor, theater, $('#heroDecisionApprove'), false), 600));
      heroTimers.push(setTimeout(() => moveCursor(cursor, theater, $('#heroDecisionApprove'), true), 1600));
    }
    scheduleHeroViewportScroll(i);
  }

  function setReviewStage(nextStage) {
    const prev = reviewStage;
    reviewStage = Math.max(0, Math.min(REVIEW.length - 1, nextStage));
    if (prev === REVIEW.length - 1 && reviewStage === 0) resetTheaterViewport(true);
    updateHero(reviewStage);
    updateTheaterStageRail(reviewStage);
    $$('#sceneDots button').forEach((d, n) => d.classList.toggle('active', n === reviewStage));
  }

  function scheduleReview() {
    clearTimeout(reviewTimer);
    if (theaterHoverPause || theaterFocusPause || theaterTabHidden || !reviewAuto || !$('.page[data-page="home"]')?.classList.contains('active')) return;
    const holdMs = reviewStage === REVIEW.length - 1 ? 3000 : 0;
    reviewTimer = setTimeout(() => {
      setReviewStage(reviewStage >= REVIEW.length - 1 ? 0 : reviewStage + 1);
      scheduleReview();
    }, REVIEW[reviewStage].duration + holdMs);
  }

  function initHeroTheater() {
    const sceneDotsEl = document.getElementById('sceneDots');
    if (sceneDotsEl) {
      REVIEW.forEach((stage, i) => {
        const b = document.createElement('button');
        b.setAttribute('aria-label', stage.label);
        b.type = 'button';
        b.onclick = () => { setReviewStage(i); scheduleReview(); };
        sceneDotsEl.appendChild(b);
      });
      $('#prevScene').onclick = () => { setReviewStage((reviewStage + REVIEW.length - 1) % REVIEW.length); scheduleReview(); };
      $('#nextScene').onclick = () => { setReviewStage((reviewStage + 1) % REVIEW.length); scheduleReview(); };
    }
    $$('#theaterStageRail span').forEach((span, i) => {
      span.onclick = () => { setReviewStage(i); scheduleReview(); };
    });
    $('#productTheater')?.addEventListener('mouseenter', (e) => {
      if (!e.isTrusted) return;
      theaterHoverPause = true;
      clearTimeout(reviewTimer);
    });
    $('#productTheater')?.addEventListener('mouseleave', (e) => {
      if (!e.isTrusted) return;
      theaterHoverPause = false;
      scheduleReview();
    });
    $('#productTheater')?.addEventListener('focusin', () => {
      theaterFocusPause = true;
      clearTimeout(reviewTimer);
    });
    $('#productTheater')?.addEventListener('focusout', (e) => {
      if ($('#productTheater')?.contains(e.relatedTarget)) return;
      theaterFocusPause = false;
      scheduleReview();
    });
    document.addEventListener('visibilitychange', () => {
      theaterTabHidden = document.hidden;
      if (theaterTabHidden) clearTimeout(reviewTimer);
      else scheduleReview();
    });
    addEventListener('resize', () => { if ($('.page[data-page="home"]')?.classList.contains('active')) updateHero(reviewStage); });

    const theater = $('#productTheater');
    if (theater) {
      theater.dataset.focus = 'upload';
      theater.dataset.reviewStage = '0';
    }
    if (reducedMotion) {
      setReviewStage(REVIEW.length - 1);
      reviewAuto = false;
    } else {
      setReviewStage(0);
      scheduleReview();
    }
  }

  function initWorkflowMotion() {
    const engine = $('#workflowEngine');
    const rail = $('#workflowRail');
    const replayBtn = $('#workflowReplay');
    if (!engine || !rail) return;

    let wfStep = 0;

    function layoutWorkflow(step) {
      const track = rail.querySelector('.workflow-track');
      const artifactTrack = $('#workflowArtifactTrack');
      const bom = $('#workflowBom');
      const fill = $('#workflowTrackFill');
      const stages = $$('.workflow-stage', rail);
      if (!track || !artifactTrack || !bom || !fill || !stages.length) return;

      const vertical = innerWidth <= 1024;
      rail.classList.toggle('is-vertical', vertical);
      const node = stages[step]?.querySelector('.workflow-node__num');
      const first = stages[0]?.querySelector('.workflow-node__num');
      const last = stages[stages.length - 1]?.querySelector('.workflow-node__num');
      if (!node || !first || !last) return;

      const railRect = rail.getBoundingClientRect();
      const trackRect = track.getBoundingClientRect();
      const artifactRect = artifactTrack.getBoundingClientRect();
      const nodeRect = node.getBoundingClientRect();
      const firstRect = first.getBoundingClientRect();
      const lastRect = last.getBoundingClientRect();

      bom.style.left = `${nodeRect.left - railRect.left + nodeRect.width / 2}px`;
      bom.style.top = `${artifactRect.top - railRect.top + artifactRect.height / 2}px`;

      if (vertical) {
        const startY = firstRect.top + firstRect.height / 2;
        const endY = nodeRect.top + nodeRect.height / 2;
        const totalY = lastRect.top + lastRect.height / 2 - startY;
        fill.style.width = '100%';
        fill.style.height = totalY ? `${Math.max(0, Math.min(100, ((endY - startY) / totalY) * 100))}%` : '0%';
      } else {
        fill.style.height = '100%';
        fill.style.width = trackRect.width ? `${Math.max(0, Math.min(100, ((nodeRect.left + nodeRect.width / 2 - trackRect.left) / trackRect.width) * 100))}%` : '0%';
      }
    }

    function applyWorkflowStep(step) {
      wfStep = step;
      engine.dataset.step = String(step);
      $$('.workflow-stage', rail).forEach((st, n) => {
        st.classList.toggle('is-active', n === step);
        st.classList.toggle('is-complete', n < step);
      });
      const cfg = WF_STEPS[step];
      if (cfg) {
        const stateEl = $(`#wfState${step}`);
        const card = rail.querySelector(`.workflow-stage[data-step="${step}"] .workflow-card__outcome`);
        const detail = rail.querySelector(`.workflow-stage[data-step="${step}"] .workflow-card small`);
        if (stateEl) stateEl.textContent = cfg.state;
        if (card) card.innerHTML = cfg.outcomeHtml;
        if (detail) detail.textContent = cfg.detail;
      }
      layoutWorkflow(step);
    }

    function resetWorkflow() {
      applyWorkflowStep(0);
    }

    function showWorkflowFinal() {
      applyWorkflowStep(WF_STEPS.length - 1);
      setReplayButton(replayBtn, false, true);
    }

    let wfLoop;
    wfLoop = createVisibleLoop({
      element: $('#workflow'),
      finalHold: 3800,
      restartDelay: 600,
      onReplayReady: (disabled, show) => setReplayButton(replayBtn, disabled, show),
      showFinal: showWorkflowFinal,
      reset: () => applyWorkflowStep(0),
      play: (ctx) => {
        let step = 0;
        applyWorkflowStep(step);
        const travelMs = 760;
        const holdMs = 1200;
        const advance = () => {
          if (!ctx.isActive()) { ctx.abort(); return; }
          step++;
          if (step >= WF_STEPS.length) { showWorkflowFinal(); launchAudit.onWorkflowCycleComplete(); ctx.complete(); return; }
          applyWorkflowStep(step);
          ctx.schedule(advance, holdMs + travelMs);
        };
        ctx.schedule(advance, holdMs + travelMs);
      }
    });

    replayBtn?.addEventListener('click', () => wfLoop.requestReplay());
    const onWfResize = () => { if (wfLoop.state.isVisible) layoutWorkflow(wfStep); };
    addEventListener('resize', onWfResize);
    registerHomeCleanup(() => {
      wfLoop.destroy();
      removeEventListener('resize', onWfResize);
    });

    if (!reducedMotion) applyWorkflowStep(0);
    else showWorkflowFinal();
    return wfLoop;
  }

  function initCommandCenterMotion() {
    const replayBtn = $('#commandReplay');

    function applyCommandStep(step, animate = true) {
      const state = commandStates[step];
      const center = $('#commandCenter');
      if (!state || !center) return;
      center.dataset.commandStep = String(step);
      center.classList.add('command-running');
      launchAudit.onCommandStep(step);
      $('#commandPhase').textContent = state.phase;
      $('#commandClock').textContent = `00:0${step * 3}`;
      if (animate && !reducedMotion) {
        animateNumber($('#cmdHealth'), state.health);
        animateNumber($('#cmdBlockers'), state.blockers);
        animateNumber($('#cmdAlerts'), state.alerts);
        animateNumber($('#cmdDecisions'), state.decisions);
        animateNumber($('#ringHealth'), state.health);
      } else {
        $('#cmdHealth').textContent = state.health;
        $('#cmdBlockers').textContent = state.blockers;
        $('#cmdAlerts').textContent = state.alerts;
        $('#cmdDecisions').textContent = state.decisions;
        $('#ringHealth').textContent = state.health;
      }
      $('#ringStatus').textContent = state.ring;
      $('#releaseHeadline').textContent = state.headline;
      $('#releaseDetail').textContent = state.detail;
      [$('#riskMpuStatus'), $('#riskLmStatus'), $('#riskTpsStatus')].forEach((el, k) => {
        if (!el) return;
        el.textContent = state.statuses[k];
        const row = el.closest('div');
        row?.classList.toggle('resolving', /Qualifying|Mitigating/.test(state.statuses[k]));
        row?.classList.toggle('resolved', /Resolved|Qualified|Monitoring/.test(state.statuses[k]));
      });
      const score = $('.score-ring .score');
      if (score) score.style.strokeDashoffset = `${314 - (314 * state.health / 100)}`;
    }

    function showCommandFinal() {
      applyCommandStep(commandStates.length - 1, false);
      setReplayButton(replayBtn, false, true);
    }

    function resetCommandStep({ soft, schedule } = {}) {
      const center = $('#commandCenter');
      if (soft && center) {
        center.classList.add('command-resetting');
        applyCommandStep(0, true);
        schedule?.(() => center.classList.remove('command-resetting'), 750);
      } else {
        center?.classList.remove('command-resetting');
        applyCommandStep(0, !reducedMotion);
      }
    }

    let cmdLoop;
    cmdLoop = createVisibleLoop({
      element: $('#commandCenter'),
      finalHold: 9000,
      restartDelay: 750,
      pauseOnHover: true,
      autoplay: HOME_SECTION_AUTOPLAY,
      onReplayReady: (disabled, show) => setReplayButton(replayBtn, disabled, show),
      showFinal: showCommandFinal,
      showIdle: () => applyCommandStep(0, false),
      reset: resetCommandStep,
      play: (ctx) => {
        let step = 0;
        applyCommandStep(0, true);
        const advance = () => {
          if (!ctx.isActive()) { ctx.abort(); return; }
          step++;
          if (step >= commandStates.length) { showCommandFinal(); launchAudit.onCommandCycleComplete(); ctx.complete(); return; }
          applyCommandStep(step, true);
          ctx.schedule(advance, 1750);
        };
        ctx.schedule(advance, 1750);
      }
    });

    replayBtn?.addEventListener('click', () => cmdLoop.requestReplay());
    registerHomeCleanup(() => cmdLoop.destroy());

    if (reducedMotion) showCommandFinal();
    else if (!HOME_SECTION_AUTOPLAY) applyCommandStep(0, false);
    return cmdLoop;
  }

  function initCopilotMotion() {
    const host = $('#copilotWorkspace');
    const shell = $('#copilotShell');
    const replayBtn = $('#copilotReplay');
    if (!host || !shell) return null;

    let copilotTyping = [];
    const answerChunks = [
      'No.',
      'Two issues currently block release.',
      'MPU6050 has lifecycle exposure.',
      'LM35DN requires a qualified second source.'
    ];

    function clearCopilotTyping() {
      copilotTyping.forEach(clearTimeout);
      copilotTyping = [];
    }

    function scheduleCopilot(fn, delay, ctx) {
      if (ctx) {
        ctx.schedule(fn, delay);
        return;
      }
      copilotTyping.push(setTimeout(fn, reducedMotion ? 0 : delay));
    }

    function typeCopilot(node, text, speed, ctx) {
      if (!node) return;
      clearCopilotTyping();
      node.textContent = '';
      if (reducedMotion) { node.textContent = text; return; }
      [...text].forEach((c, i) => {
        const id = setTimeout(() => {
          if (ctx && !ctx.isActive()) return;
          node.textContent += c;
        }, i * speed);
        copilotTyping.push(id);
      });
    }

    function streamCopilotChunks(node, chunks, gap, ctx, onDone) {
      if (!node) return;
      clearCopilotTyping();
      if (reducedMotion) {
        node.textContent = chunks.join(' ');
        onDone?.();
        return;
      }
      node.textContent = '';
      let ci = 0;
      const addChunk = () => {
        if (ctx && !ctx.isActive()) return;
        if (ci >= chunks.length) { onDone?.(); return; }
        node.textContent += (ci ? ' ' : '') + chunks[ci++];
        scheduleCopilot(addChunk, gap, ctx);
      };
      addChunk();
    }

    function setCopilotIdleShell() {
      shell.classList.remove('copilot-shell--resetting', 'copilot-shell--answered');
      $('#copilotShellState').textContent = 'Ready for engineer question';
      $('#copilotQuestionText').textContent = 'Ask a production-readiness question…';
      $('#copilotInputField')?.classList.remove('typing', 'demo-target');
      $('#copilotAnswerText').textContent = 'Analyzing motor_controller_rev_c.xlsx for release blockers and supplier exposure.';
      $('#copilotConfidence').textContent = 'Reviewing evidence…';
      const blockers = $('#copilotBlockers');
      const mitigation = $('#copilotMitigation');
      if (blockers) blockers.innerHTML = '<span class="skeleton">Blocking components will appear here</span>';
      if (mitigation) mitigation.textContent = 'Recommended mitigation will appear after evidence review completes.';
      $('#copilotCreateDecision').disabled = true;
      $$('#copilotReasoning article').forEach(r => { r.classList.remove('active', 'done'); r.querySelector('em').textContent = 'Waiting'; });
      $$('#copilotEvidenceRail span').forEach(e => e.classList.remove('active', 'done'));
      $('#copilotSupplierEvidence')?.classList.remove('updated');
      hideCursor($('#copilotCursor'));
    }

    function softResetCopilotShell({ soft = true, schedule } = {}) {
      if (soft === false) {
        clearCopilotTyping();
        hideCursor($('#copilotCursor'));
        shell.classList.remove('copilot-shell--resetting', 'copilot-shell--answered');
        setCopilotIdleShell();
        return;
      }
      clearCopilotTyping();
      hideCursor($('#copilotCursor'));
      shell.classList.add('copilot-shell--resetting');
      shell.classList.remove('copilot-shell--answered');
      $('#copilotShellState').textContent = 'Preparing next review';
      $('#copilotInputField')?.classList.remove('typing', 'demo-target');
      const qNode = $('#copilotQuestionText');
      if (qNode && qNode.textContent.length > 0 && !reducedMotion) {
        let i = qNode.textContent.length;
        const erase = () => {
          if (i <= 0) {
            qNode.textContent = 'Ask a production-readiness question…';
            return;
          }
          qNode.textContent = qNode.textContent.slice(0, -1);
          i--;
          schedule?.(erase, 16);
        };
        erase();
      } else if (qNode) {
        qNode.textContent = 'Ask a production-readiness question…';
      }
      $('#copilotConfidence').textContent = 'Reviewing evidence…';
      $('#copilotCreateDecision').disabled = true;
      $$('#copilotReasoning article').forEach(r => { r.classList.remove('active', 'done'); r.querySelector('em').textContent = 'Waiting'; });
      $$('#copilotEvidenceRail span').forEach(e => e.classList.remove('active', 'done'));
      $('#copilotSupplierEvidence')?.classList.remove('updated');
      shell.scrollTo?.({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' });
      const finishReset = () => {
        shell.classList.remove('copilot-shell--resetting');
        $('#copilotAnswerText').textContent = 'Analyzing motor_controller_rev_c.xlsx for release blockers and supplier exposure.';
        const blockers = $('#copilotBlockers');
        const mitigation = $('#copilotMitigation');
        if (blockers) blockers.innerHTML = '<span class="skeleton">Blocking components will appear here</span>';
        if (mitigation) mitigation.textContent = 'Recommended mitigation will appear after evidence review completes.';
      };
      if (schedule) schedule(finishReset, 650);
      else finishReset();
    }

    function setCopilotFinalShell() {
      shell.classList.remove('copilot-shell--resetting');
      shell.classList.add('copilot-shell--answered');
      $('#copilotShellState').textContent = 'Recommendation ready';
      $('#copilotQuestionText').textContent = q;
      $('#copilotInputField')?.classList.remove('typing');
      $('#copilotAnswerText').textContent = answerChunks.join(' ');
      $('#copilotConfidence').textContent = '93% confidence';
      $('#copilotBlockers').innerHTML = '<span>MPU6050 · EOL blocker</span><span>LM35DN · single-source exposure</span>';
      $('#copilotMitigation').textContent = 'Qualify LM35DN second source and replace MPU6050 before production release.';
      $('#copilotCreateDecision').disabled = false;
      $$('#copilotReasoning article').forEach(r => { r.classList.remove('active'); r.classList.add('done'); r.querySelector('em').textContent = 'Complete'; });
      $$('#copilotEvidenceRail span').forEach(e => { e.classList.add('done'); e.classList.remove('active'); });
      $('#copilotSupplierEvidence')?.classList.add('updated');
    }

    let copilotLoop;
    copilotLoop = createVisibleLoop({
      element: host,
      finalHold: 9000,
      restartDelay: 650,
      pauseOnHover: true,
      pauseOnFocus: true,
      autoplay: HOME_SECTION_AUTOPLAY,
      onReplayReady: (disabled, show) => setReplayButton(replayBtn, disabled, show),
      showFinal: setCopilotFinalShell,
      showIdle: setCopilotIdleShell,
      reset: softResetCopilotShell,
      play: (ctx) => {
        clearCopilotTyping();
        shell.classList.remove('copilot-shell--resetting', 'copilot-shell--answered');
        setCopilotIdleShell();

        ctx.schedule(() => {
          if (!ctx.isActive()) return;
          $('#copilotShellState').textContent = 'Engineer typing question';
          $('#copilotInputField')?.classList.add('typing');
          typeCopilot($('#copilotQuestionText'), q, 34, ctx);
          ctx.schedule(() => moveCursor($('#copilotCursor'), host, $('#copilotInputField'), false), 320);
          ctx.schedule(() => moveCursor($('#copilotCursor'), host, $('#copilotInputField'), true), 1200);
        }, 280);

        ctx.schedule(() => {
          if (!ctx.isActive()) { ctx.abort(); return; }
          $('#copilotShellState').textContent = 'Cadivor reviewing evidence';
          $('#copilotInputField')?.classList.remove('typing');
          hideCursor($('#copilotCursor'));
          $('#copilotConfidence').textContent = 'Reasoning…';
          const reasoning = $$('#copilotReasoning article');
          const evidence = $$('#copilotEvidenceRail span');
          reasoning.forEach((r, ri) => {
            ctx.schedule(() => {
              if (!ctx.isActive()) return;
              reasoning.forEach((x, xi) => {
                x.classList.toggle('active', xi === ri);
                x.classList.toggle('done', xi < ri);
                x.querySelector('em').textContent = xi < ri ? 'Complete' : 'Reviewing';
              });
              evidence[ri]?.classList.add('done');
              evidence[ri + 1]?.classList.add('active');
            }, ri * 280);
          });
          ctx.schedule(() => $('#copilotSupplierEvidence')?.classList.add('updated'), 1600);
        }, 2100);

        ctx.schedule(() => {
          if (!ctx.isActive()) { ctx.abort(); return; }
          $('#copilotShellState').textContent = 'Recommendation streaming';
          streamCopilotChunks($('#copilotAnswerText'), answerChunks, 320, ctx, () => {
            if (!ctx.isActive()) return;
            $('#copilotConfidence').textContent = '93% confidence';
            $('#copilotBlockers').innerHTML = '<span>MPU6050 · EOL blocker</span><span>LM35DN · single-source exposure</span>';
            $('#copilotMitigation').textContent = 'Qualify LM35DN second source and replace MPU6050 before production release.';
            $('#copilotCreateDecision').disabled = false;
            $('#copilotShellState').textContent = 'Recommendation ready';
            shell.classList.add('copilot-shell--answered');
            ctx.schedule(() => moveCursor($('#copilotCursor'), host, $('#copilotCreateDecision'), false), 280);
            ctx.schedule(() => moveCursor($('#copilotCursor'), host, $('#copilotCreateDecision'), true), 900);
            ctx.complete();
            launchAudit.onCopilotCycleComplete();
          });
        }, 4000);
      }
    });

    replayBtn?.addEventListener('click', () => copilotLoop.requestReplay());
    registerHomeCleanup(() => {
      clearCopilotTyping();
      copilotLoop.destroy();
    });

    setCopilotIdleShell();
    return copilotLoop;
  }

  function centerWithin(container, element) {
    const containerRect = container.getBoundingClientRect();
    const rect = element.getBoundingClientRect();
    return {
      x: rect.left - containerRect.left + rect.width / 2,
      y: rect.top - containerRect.top + rect.height / 2
    };
  }

  function initSupplierIntelligence() {
    const network = $('#supplierNetwork');
    const lines = $('#supplierNetworkLines');
    const workspace = $('#supplierWorkspace');
    if (!network || !lines || !workspace) return null;

    const pathIds = ['pathDigiKey', 'pathMouser', 'pathNewark'];
    const supplierData = [
      { name: 'DigiKey', availability: '42,860', lead: '8 weeks', concentration: 'Reduced 38%', altQual: 'Qualified', score: '94', reason: 'Highest authorized inventory with the shortest verified lead time.' },
      { name: 'Mouser', availability: '31,240', lead: '10 weeks', concentration: 'Reduced 31%', altQual: 'Qualified', score: '86', reason: 'Strong global availability and a validated secondary procurement path.' },
      { name: 'Newark', availability: '9,810', lead: '12 weeks', concentration: 'Reduced 17%', altQual: 'Available', score: '71', reason: 'Useful regional coverage, but lower available inventory and longer lead time.' }
    ];

    let cycleIndex = 0;
    let manualPaused = false;
    let manualResumeTimer = null;
    let resizeObserver = null;
    let onResize = null;
    let pathDebounce = null;

    function clearManualResume() {
      if (manualResumeTimer) { clearTimeout(manualResumeTimer); manualResumeTimer = null; }
    }

    function scheduleSupplierPaths() {
      if (pathDebounce) clearTimeout(pathDebounce);
      pathDebounce = setTimeout(() => {
        pathDebounce = null;
        updateSupplierPaths();
      }, 80);
    }

    function updateSupplierPaths() {
      if (innerWidth <= 768) {
        $$('.supplier-path', lines).forEach(p => p.removeAttribute('d'));
        return;
      }
      const layout = $('.supplier-layout', workspace);
      const container = layout || network;
      if (layout && lines.parentElement !== layout) {
        layout.insertBefore(lines, layout.firstChild);
      }
      const dest = $('#supplierPathDestination') || $('#supplierQualSummary');
      if (!dest) return;
      const w = Math.max(container.clientWidth, 1);
      const h = Math.max(container.clientHeight, 1);
      lines.setAttribute('viewBox', `0 0 ${w} ${h}`);
      lines.setAttribute('width', String(w));
      lines.setAttribute('height', String(h));
      const end = centerWithin(container, dest);
      $$('.supplier-node', network).forEach((node, i) => {
        const path = $(`#${pathIds[i]}`);
        if (!path) return;
        const start = centerWithin(container, node);
        const ctrlX = (start.x + end.x) / 2;
        const lift = Math.max(28, Math.min(64, Math.abs(start.x - end.x) * 0.12));
        const ctrlY = Math.min(start.y, end.y) - lift;
        path.setAttribute('d', `M ${start.x} ${start.y} Q ${ctrlX} ${ctrlY} ${end.x} ${end.y}`);
      });
    }

    function selectSupplier(i, fromUser = false) {
      cycleIndex = i;
      const insight = $('.supplier-insight', workspace);
      insight?.classList.add('is-updating');
      $$('.supplier-node', network).forEach((n, j) => n.classList.toggle('active', i === j));
      $$('#supplierComparisonTable button').forEach((n, j) => n.classList.toggle('selected', i === j));
      $$('.supplier-path', lines).forEach((p, j) => {
        p.classList.toggle('active', i === j);
        p.classList.toggle('subdued', i !== j);
      });
      const d = supplierData[i];
      if (!d) return;
      const tableBtn = $$('#supplierComparisonTable button')[i];
      const statusLabels = ['Recommended', 'Qualified', 'Available'];
      const rec = $('#supplierRecommendation');
      if (rec) {
        rec.style.opacity = '0';
        rec.style.transform = 'translateY(6px)';
        requestAnimationFrame(() => {
          rec.textContent = `${d.name} is ${i === 0 ? 'the preferred' : 'a qualified'} source.`;
          rec.style.opacity = '1';
          rec.style.transform = 'translateY(0)';
        });
      }
      $('#supplierAltQual').textContent = d.altQual;
      if ($('#supplierStatus')) $('#supplierStatus').textContent = statusLabels[i] || 'Qualified';
      const qualInv = $('#qualInventory');
      if (qualInv) {
        qualInv.textContent = d.availability;
        qualInv.classList.remove('inventory-tick');
        void qualInv.offsetWidth;
        qualInv.classList.add('inventory-tick');
      }
      $('#qualLead') && ($('#qualLead').textContent = d.lead);
      $('#qualConcentration') && ($('#qualConcentration').textContent = d.concentration);
      $('#qualRationale') && ($('#qualRationale').textContent = d.reason);
      setTimeout(() => insight?.classList.remove('is-updating'), 380);
      if (tableBtn) {
        const spans = $$('span', tableBtn);
        if (spans[0] && $('#supplierAuth')) $('#supplierAuth').textContent = spans[0].textContent;
        if (spans[4] && $('#supplierRegion')) $('#supplierRegion').textContent = spans[4].textContent;
        if (spans[5] && $('#qualLifecycle')) $('#qualLifecycle').textContent = spans[5].textContent;
        if (spans[7]) spans[7].textContent = d.altQual;
        if (spans[8]) spans[8].textContent = d.score;
        const statusEl = $('em', tableBtn);
        if (statusEl) statusEl.textContent = statusLabels[i] || statusEl.textContent;
      }
      requestAnimationFrame(scheduleSupplierPaths);
      launchAudit.onSupplierSelect(i, fromUser);
      if (fromUser) manualPaused = true;
    }

    let supplierLoop;
    selectSupplier(0, false);

    supplierLoop = createVisibleLoop({
      element: workspace,
      pauseOnHover: true,
      pauseOnFocus: true,
      autoplay: HOME_SECTION_AUTOPLAY,
      showFinal: () => selectSupplier(0, false),
      showIdle: () => selectSupplier(0, false),
      play: (ctx) => {
        manualPaused = false;
        const advance = () => {
          if (!ctx.isActive()) { ctx.abort(); return; }
          if (manualPaused) {
            ctx.schedule(advance, 300);
            return;
          }
          cycleIndex = (cycleIndex + 1) % supplierData.length;
          selectSupplier(cycleIndex, false);
          ctx.schedule(advance, 4000);
        };
        ctx.schedule(advance, 4000);
      },
      reset: () => {}
    });

    function bindSupplierClick(i) {
      selectSupplier(i, true);
      clearManualResume();
      if (!HOME_SECTION_AUTOPLAY) return;
      manualResumeTimer = setTimeout(() => {
        manualPaused = false;
        if (supplierLoop.state.isVisible && !supplierLoop.state.isPlaying && !reducedMotion) {
          supplierLoop.beginCycle();
        }
      }, 9000);
    }

    $$('.supplier-node', network).forEach((n, i) => { n.onclick = () => bindSupplierClick(i); });
    $$('#supplierComparisonTable button').forEach((n, i) => { n.onclick = () => bindSupplierClick(i); });

    resizeObserver = new ResizeObserver(scheduleSupplierPaths);
    resizeObserver.observe(network);
    resizeObserver.observe(workspace);
    const layout = $('.supplier-layout', workspace);
    if (layout) resizeObserver.observe(layout);
    const tableWrap = $('.supplier-table-wrap', workspace);
    const qualSummary = $('#supplierQualSummary', workspace);
    if (tableWrap) resizeObserver.observe(tableWrap);
    if (qualSummary) resizeObserver.observe(qualSummary);
    document.fonts?.ready?.then(scheduleSupplierPaths).catch(() => scheduleSupplierPaths());
    onResize = () => scheduleSupplierPaths();
    addEventListener('resize', onResize);

    registerHomeCleanup(() => {
      clearManualResume();
      if (pathDebounce) clearTimeout(pathDebounce);
      resizeObserver?.disconnect();
      if (onResize) removeEventListener('resize', onResize);
      supplierLoop.destroy();
    });

    return { destroy: () => supplierLoop.destroy(), refresh: scheduleSupplierPaths };
  }

  function initDecisionRecordMotion() {
    const record = $('#decisionRecord');
    const section = record?.closest('.decision-showcase');
    const approveBtn = $('#approveDecision');
    if (!record || !approveBtn || !section) return null;

    const confidenceEl = $('#recordConfidence');
    const evidenceEl = $('#recordEvidence');
    const ownerEl = $('#recordOwner');
    const statusEl = $('#recordStatus');
    const monitorEl = $('#recordMonitor');
    const monitorSwitch = $('#monitorSwitch');
    const monitorLabel = $('#monitorSwitchLabel');
    const approvedBadge = $('#recordApprovedBadge');
    const timeline = $('#engineeringTimeline');
    const timelineNodes = $$('.timeline-node', timeline);
    const decisionLines = $$('.decision-line', record);
    const signatureName = $('#signatureName');
    const signatureTime = $('#signatureTime');

    let decisionTimers = [];
    let decisionObserver = null;
    let sequenceToken = 0;

    function clearDecisionTimers() {
      decisionTimers.forEach(t => clearTimeout(t));
      decisionTimers = [];
    }

    function schedule(fn, delay) {
      const token = sequenceToken;
      decisionTimers.push(setTimeout(() => {
        if (token !== sequenceToken) return;
        fn();
      }, delay));
    }

    function animatePercent(el, target) {
      if (!el) return;
      if (reducedMotion) { el.textContent = `${target}%`; return; }
      let step = 0;
      const tick = setInterval(() => {
        step++;
        el.textContent = `${Math.round((target * step) / MOTION.steps)}%`;
        if (step >= MOTION.steps) {
          clearInterval(tick);
          el.textContent = `${target}%`;
        }
      }, MOTION.tick);
    }

    function animateSources(el, target) {
      if (!el) return;
      if (reducedMotion) { el.textContent = `${target} sources`; return; }
      let step = 0;
      const tick = setInterval(() => {
        step++;
        el.textContent = `${Math.round((target * step) / MOTION.steps)} sources`;
        if (step >= MOTION.steps) {
          clearInterval(tick);
          el.textContent = `${target} sources`;
        }
      }, MOTION.tick);
    }

    function fadeMonitoringLabel(el, text) {
      if (!el) return;
      if (reducedMotion) { el.textContent = text; return; }
      el.classList.add('is-fading');
      schedule(() => {
        el.textContent = text;
        el.classList.remove('is-fading');
        el.classList.add('is-active');
      }, MOTION.fast);
    }

    function resetDecisionPresentation() {
      sequenceToken++;
      clearDecisionTimers();
      record.classList.remove('approved', 'signing', 'decision-sequence-active', 'decision-sequence-complete');
      approveBtn.textContent = 'Approve decision';
      approveBtn.disabled = false;
      if (statusEl) statusEl.textContent = 'READY FOR APPROVAL';
      if (ownerEl) { ownerEl.textContent = '—'; ownerEl.classList.remove('is-visible'); }
      if (confidenceEl) confidenceEl.textContent = '0%';
      if (evidenceEl) evidenceEl.textContent = '0 sources';
      if (monitorEl) { monitorEl.textContent = 'Pending'; monitorEl.classList.remove('is-active', 'is-fading'); }
      if (monitorLabel) { monitorLabel.textContent = 'Pending'; monitorLabel.classList.remove('is-active', 'is-fading'); }
      monitorSwitch?.classList.remove('is-active');
      approvedBadge?.classList.remove('is-visible');
      approvedBadge?.setAttribute('hidden', '');
      timelineNodes.forEach(n => n.classList.remove('done', 'is-current'));
      decisionLines.forEach(l => l.classList.remove('is-visible'));
      if (signatureName) signatureName.textContent = 'Awaiting signature';
      if (signatureTime) signatureTime.textContent = '—';
    }

    function applyFinalDecisionState() {
      record.classList.add('approved', 'signing', 'decision-sequence-complete');
      approveBtn.textContent = '✓ Approved';
      approveBtn.disabled = true;
      if (statusEl) statusEl.textContent = 'APPROVED';
      if (ownerEl) { ownerEl.textContent = 'Jordan Ellis'; ownerEl.classList.add('is-visible'); }
      if (confidenceEl) confidenceEl.textContent = '93%';
      if (evidenceEl) evidenceEl.textContent = '14 sources';
      if (monitorEl) { monitorEl.textContent = 'Active'; monitorEl.classList.add('is-active'); }
      if (monitorLabel) { monitorLabel.textContent = 'Active'; monitorLabel.classList.add('is-active'); }
      monitorSwitch?.classList.add('is-active');
      approvedBadge?.removeAttribute('hidden');
      approvedBadge?.classList.add('is-visible');
      timelineNodes.forEach(n => n.classList.add('done'));
      decisionLines.forEach(l => l.classList.add('is-visible'));
      if (signatureName) signatureName.textContent = 'Jordan Ellis';
      if (signatureTime) signatureTime.textContent = 'Approved moments ago · Evidence hash EV-84A2';
      schedule(() => record.classList.remove('signing'), 900);
    }

    function runDecisionSequence() {
      resetDecisionPresentation();
      record.classList.add('decision-sequence-active');

      if (reducedMotion) {
        applyFinalDecisionState();
        return;
      }

      schedule(() => {
        animatePercent(confidenceEl, 93);
        animateSources(evidenceEl, 14);
      }, MOTION.fast);

      schedule(() => {
        if (ownerEl) {
          ownerEl.textContent = 'Jordan Ellis';
          ownerEl.classList.add('is-visible');
        }
      }, MOTION.standard - 100);

      decisionLines.forEach((line, i) => {
        schedule(() => line.classList.add('is-visible'), MOTION.standard + 460 + i * MOTION.fast);
      });

      timelineNodes.forEach((node, i) => {
        schedule(() => {
          timelineNodes.forEach((n, j) => n.classList.toggle('is-current', j === i));
          node.classList.add('done');
        }, MOTION.standard + 1380 + i * (MOTION.standard + 100));
      });

      schedule(() => {
        approveBtn.textContent = '✓ Approved';
        approveBtn.disabled = true;
        if (statusEl) statusEl.textContent = 'APPROVED';
        approvedBadge?.removeAttribute('hidden');
        approvedBadge?.classList.add('is-visible');
        record.classList.add('approved', 'signing');
        if (signatureName) signatureName.textContent = 'Jordan Ellis';
        if (signatureTime) signatureTime.textContent = 'Approved moments ago · Evidence hash EV-84A2';
        schedule(() => record.classList.remove('signing'), MOTION.standard + 80);
      }, MOTION.standard + 1380 + 2 * (MOTION.standard + 100) + 120);

      schedule(() => {
        fadeMonitoringLabel(monitorEl, 'Active');
        fadeMonitoringLabel(monitorLabel, 'Active');
        monitorSwitch?.classList.add('is-active');
        record.classList.add('decision-sequence-complete');
      }, MOTION.standard + 1380 + 3 * (MOTION.standard + 100) + 80);
    }

    decisionObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          if (HOME_SECTION_AUTOPLAY) runDecisionSequence();
          else resetDecisionPresentation();
        } else {
          resetDecisionPresentation();
        }
      });
    }, { threshold: 0.35 });

    decisionObserver.observe(section);

    approveBtn.addEventListener('click', () => {
      if (record.classList.contains('approved')) return;
      sequenceToken++;
      clearDecisionTimers();
      applyFinalDecisionState();
    });

    const destroy = () => {
      sequenceToken++;
      clearDecisionTimers();
      decisionObserver?.disconnect();
    };
    registerHomeCleanup(destroy);
    return { destroy };
  }

  let homeInitialized = false;

  function initHomePage() {
    if (homeInitialized) return;
    try {
      homeInitialized = true;
      launchAudit.onHomeInit();
      initHeroTheater();
      registerHomeCleanup(() => {
        clearTimeout(reviewTimer);
        clearHeroTimers();
        reviewAuto = false;
      });
      initWorkflowMotion();
      initCommandCenterMotion();
      initCopilotMotion();
      initSupplierIntelligence();
      initDecisionRecordMotion();

      const sceneObservers = [];
      $$('.page[data-page="home"] .experience-scene').forEach(scene => {
        const obs = new IntersectionObserver(entries => entries.forEach(e => {
          if (e.isIntersecting) scene.classList.add('scene-active');
        }), { threshold: 0.28 });
        obs.observe(scene);
        sceneObservers.push(obs);
      });
      $$('.page[data-page="home"] .scene-transition').forEach(t => {
        const obs = new IntersectionObserver(entries => entries.forEach(e => e.target.classList.toggle('in-view', e.isIntersecting)), { threshold: 0.35 });
        obs.observe(t);
        sceneObservers.push(obs);
      });
      registerHomeCleanup(() => sceneObservers.forEach(o => o.disconnect()));
    } catch (err) {
      homeInitialized = false;
      console.error('Cadivor motion init failed:', err);
      document.body.dataset.motionInitError = err?.message || 'unknown';
    }
  }

  function syncHomeMode() {
    const home = $('.page[data-page="home"]')?.classList.contains('active');
    document.body.classList.toggle('experience-home', !!home);
    if (home) {
      initHomePage();
      if (!reducedMotion) scheduleReview();
      else setReviewStage(REVIEW.length - 1);
    } else {
      cleanupHomePage();
      homeInitialized = false;
      clearTimeout(reviewTimer);
      clearHeroTimers();
      reviewAuto = !reducedMotion;
    }
  }

  function initProductPageDemos() {
    const cmdStates = [
      { phase: 'Baseline risk posture', health: 72, blockers: 4, alerts: 17, decisions: 16 },
      { phase: 'Mitigation in progress', health: 89, blockers: 1, alerts: 8, decisions: 17 },
      { phase: 'Release posture resolved', health: 96, blockers: 0, alerts: 5, decisions: 18 }
    ];
    const cmdDemo = $('#productCommandDemo');
    if (cmdDemo) {
      let cmdPlaying = false;
      let cmdTimer = null;
      const applyCmd = (s, animate = false) => {
        $('#productCmdPhase').textContent = s.phase;
        const fields = [
          ['#productCmdHealth', s.health],
          ['#productCmdBlockers', s.blockers],
          ['#productCmdAlerts', s.alerts],
          ['#productCmdDecisions', s.decisions]
        ];
        fields.forEach(([sel, val], idx) => {
          const el = $(sel);
          if (!el) return;
          if (animate && !reducedMotion) {
            setTimeout(() => animateNumber(el, val), idx * 80);
          } else {
            el.textContent = val;
          }
        });
      };
      const resetCmd = () => {
        cmdPlaying = false;
        if (cmdTimer) clearTimeout(cmdTimer);
        cmdTimer = null;
        applyCmd(cmdStates[0], false);
      };
      const runCmd = () => {
        if (reducedMotion) {
          applyCmd(cmdStates[cmdStates.length - 1], false);
          return;
        }
        if (cmdPlaying) return;
        cmdPlaying = true;
        applyCmd(cmdStates[0], true);
        let step = 0;
        const tick = () => {
          step++;
          if (step >= cmdStates.length) {
            cmdPlaying = false;
            return;
          }
          applyCmd(cmdStates[step], true);
          cmdTimer = setTimeout(tick, 1800);
        };
        cmdTimer = setTimeout(tick, 1200);
      };
      new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) runCmd();
          else resetCmd();
        });
      }, { threshold: 0.45 }).observe(cmdDemo);
    }

    $$('.page[data-page="product"] .product-module__metrics').forEach(metrics => {
      new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) {
            delete metrics.dataset.animated;
            return;
          }
          if (metrics.dataset.animated) return;
          metrics.dataset.animated = '1';
          $$('b', metrics).forEach(b => animateMetricText(b));
        });
      }, { threshold: 0.35 }).observe(metrics);
    });

    const copilotDemo = $('#productCopilotDemo');
    if (copilotDemo) {
      let played = false;
      let copilotObserver = null;
      const runCopilot = () => {
        if (played && !reducedMotion) return;
        played = true;
        $('#productCopilotState').textContent = 'Reviewing evidence';
        type($('#productCopilotQ'), q, 18);
        setTimeout(() => {
          streamChunks($('#productCopilotA'), [
            'No.',
            'Two issues block release.',
            'Qualify LM35DN second source and replace MPU6050 before approval.'
          ], reducedMotion ? 0 : 260, () => {
            $('#productCopilotState').textContent = '93% confidence';
          });
        }, reducedMotion ? 0 : 1400);
      };
      const resetCopilot = () => {
        played = false;
        $('#productCopilotState').textContent = 'Ready';
        $('#productCopilotQ').textContent = q;
        $('#productCopilotA').textContent = 'Analyzing release blockers and supplier exposure…';
      };
      copilotObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) runCopilot();
          else resetCopilot();
        });
      }, { threshold: 0.45 });
      copilotObserver.observe(copilotDemo);
    }

    const supplierRows = $$('[data-ps-supplier]', $('#product-supplier'));
    const rec = $('#productSupplierRec');
    const psData = ['DigiKey is the preferred qualification source.', 'Mouser is a qualified secondary source.', 'Newark provides regional coverage with lower inventory.'];
    supplierRows.forEach(row => {
      row.style.cursor = 'pointer';
      row.onclick = () => {
        supplierRows.forEach(r => r.classList.remove('selected'));
        row.classList.add('selected');
        if (rec) rec.textContent = psData[Number(row.dataset.psSupplier)] || psData[0];
      };
    });
  }

  function initSolutionsDemos() {
    const solScene = $('#solution-supply');
    const solRows = $$('[data-sol-supplier]');
    const solRec = $('#solutionSupplierRec');
    const solData = ['DigiKey recommended', 'Mouser qualified', 'Newark available'];
    let solIndex = 0;
    let solTimer = null;
    let solObserver = null;

    function selectSolutionSupplier(i, fromUser = false) {
      solIndex = i;
      solRows.forEach((row, j) => {
        row.classList.toggle('selected', j === i);
        row.classList.toggle('sol-row-active', j === i);
      });
      if (solRec) solRec.textContent = solData[i] || solData[0];
      if (fromUser) {
        if (solTimer) clearInterval(solTimer);
        solTimer = setTimeout(() => startSolutionSupplierCycle(), 8000);
      }
    }

    function startSolutionSupplierCycle() {
      if (solTimer) clearInterval(solTimer);
      if (reducedMotion || !solScene) return;
      solTimer = setInterval(() => {
        solIndex = (solIndex + 1) % solRows.length;
        selectSolutionSupplier(solIndex, false);
      }, 3200);
    }

    solRows.forEach((row, i) => {
      row.style.cursor = 'pointer';
      row.onclick = () => selectSolutionSupplier(i, true);
    });

    if (solScene) {
      solObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (entry.isIntersecting) startSolutionSupplierCycle();
          else if (solTimer) { clearInterval(solTimer); solTimer = null; }
        });
      }, { threshold: 0.35 });
      solObserver.observe(solScene);
    }

    $$('.page[data-page="solutions"] [data-solution-kpi]').forEach(row => {
      const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          if (!entry.isIntersecting) {
            delete row.dataset.counted;
            $$('strong[data-count-target]', row).forEach(el => { el.textContent = '0'; });
            return;
          }
          if (row.dataset.counted) return;
          row.dataset.counted = '1';
          $$('strong[data-count-target]', row).forEach(el => {
            animateNumber(el, Number(el.dataset.countTarget));
          });
        });
      }, { threshold: 0.4 });
      observer.observe(row);
    });
  }

  function initResourceModals() {
    const modal = $('#resourceModal');
    if (!modal) return;
    const title = $('#resourceModalTitle');
    const desc = $('#resourceModalDesc');
    const label = $('#resourceModalLabel');
    const labels = { preview: 'PREVIEW', 'sample-output': 'SAMPLE OUTPUT', 'open-example': 'OPEN EXAMPLE', sample: 'SAMPLE OUTPUT', download: 'OPEN EXAMPLE' };

    function closeModal() {
      modal.classList.remove('is-open');
      document.body.style.overflow = '';
      setTimeout(() => {
        modal.hidden = true;
        modal.setAttribute('aria-hidden', 'true');
      }, reducedMotion ? 0 : MOTION.standard);
    }

    function openModal(type, modalTitle, modalDesc) {
      if (label) label.textContent = labels[type] || 'PREVIEW';
      if (title) title.textContent = modalTitle || 'Resource preview';
      if (desc) desc.textContent = modalDesc || '';
      modal.hidden = false;
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      requestAnimationFrame(() => modal.classList.add('is-open'));
    }

    $$('[data-resource-modal]').forEach(btn => {
      btn.addEventListener('click', () => {
        openModal(btn.dataset.resourceModal, btn.dataset.resourceTitle, btn.dataset.resourceDesc);
      });
    });
    $$('[data-resource-close]', modal).forEach(el => el.addEventListener('click', closeModal));
    addEventListener('keydown', e => {
      if (e.key === 'Escape' && !modal.hidden) closeModal();
    });
  }

  function initContactForm() {
    const form = $('#contactForm');
    const card = $('#contactFormCard');
    const success = $('#contactSuccess');
    const resetBtn = $('#contactReset');
    const submitBtn = $('#contactSubmit');
    const status = $('#formStatus');
    if (!form) return;

    resetBtn?.addEventListener('click', () => {
      card?.classList.remove('is-success');
      success?.setAttribute('hidden', '');
      form.reset();
      if (status) status.textContent = 'This form opens your email client with the completed request.';
    });

    form.addEventListener('submit', e => {
      e.preventDefault();
      const f = new FormData(form);
      const name = String(f.get('name') || '').trim();
      const email = String(f.get('email') || '').trim();
      const message = String(f.get('message') || '').trim();
      if (!name || !email || !message) {
        if (status) status.textContent = 'Please complete all required fields before submitting.';
        return;
      }
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
        if (status) status.textContent = 'Enter a valid work email address.';
        return;
      }
      const subject = encodeURIComponent(`Cadivor demo request from ${name}`);
      const body = encodeURIComponent(`Name: ${name}\nEmail: ${email}\nCompany: ${f.get('company')}\n\n${message}`);
      submitBtn?.classList.add('is-submitting');
      if (status) status.textContent = 'Preparing your request…';
      const mailto = `mailto:info@cadivor.com?subject=${subject}&body=${body}`;
      setTimeout(() => {
        submitBtn?.classList.remove('is-submitting');
        card?.classList.add('is-success');
        success?.removeAttribute('hidden');
        if (status) status.textContent = '';
        setTimeout(() => { location.href = mailto; }, reducedMotion ? 0 : MOTION.standard + 160);
      }, reducedMotion ? 0 : MOTION.standard - 40);
    });
  }

  initProductPageDemos();
  initSolutionsDemos();
  initResourceModals();
  initContactForm();
  initKpiCards();
  refreshGlobalMotion();

  $$('.billing-toggle button').forEach(b => b.onclick = () => {
    $$('.billing-toggle button').forEach(x => x.classList.remove('active'));
    b.classList.add('active');
  });

  if (launchAudit.enabled) {
    setTimeout(() => launchAudit.finalize(), 120000);
  }

  route();
})();

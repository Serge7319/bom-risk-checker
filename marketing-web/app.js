(() => {
  const APP_URL = window.CADIVOR_APP_URL || 'https://app.cadivor.com';
  document.querySelectorAll('.app-link').forEach((link) => {
    const auth = link.getAttribute('data-auth') || 'login';
    link.setAttribute('href', `${APP_URL}?auth=${encodeURIComponent(auth)}`);
  });

  const question = 'Is this BOM ready for production release?';
  const answer = 'No. Two issues block release. Qualify the LM35DN second source and replace the MPU6050 before approval.';
  const stageCopy = [
    'Ready for a BOM',
    'Uploading motor_controller_rev_c.xlsx',
    'Analyzing 1,842 component records',
    'Cadivor is gathering engineering evidence',
    'Recommendation ready for review',
    'Decision approved — monitoring active',
  ];
  const durations = [850, 1450, 2050, 2500, 2450, 2100];
  let stage = 0;
  let timer = null;
  let paused = false;
  let typingTimers = [];

  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const elements = {
    theater: $('#productTheater'),
    file: $('#fileOrbit'), cursor: $('#demoCursor'), state: $('#analysisState'), phase: $('#phaseFill'),
    upload: $('#uploadState'), uploadProgress: $('#uploadProgress'), health: $('#healthValue'), blockers: $('#blockerValue'),
    alerts: $('#alertValue'), alternates: $('#alternateValue'), question: $('#questionText'), qCaret: $('#questionCaret'),
    thinking: $('#thinking'), ai: $('#chatAi'), answer: $('#answerText'), confidence: $('#confidenceLabel'),
    actions: $('#decisionActions'), toast: $('#approvalToast'), life: $('#lifeEvidence'), supply: $('#supplyEvidence'), decision: $('#decisionEvidence'),
  };

  function clearTyping() { typingTimers.forEach(clearTimeout); typingTimers = []; }
  function typeText(node, text, speed, delay = 0) {
    node.textContent = '';
    [...text].forEach((char, index) => {
      typingTimers.push(setTimeout(() => { node.textContent += char; }, delay + index * speed));
    });
  }

  function renderStage(next) {
    stage = next;
    clearTyping();
    elements.state.textContent = stageCopy[stage];
    elements.phase.style.width = `${[5, 20, 48, 70, 88, 100][stage]}%`;
    elements.file.classList.toggle('active', stage === 1);
    elements.cursor.className = `cursor s${stage}`;
    elements.upload.textContent = stage >= 2 ? 'Imported' : stage === 1 ? 'Uploading…' : 'Waiting';
    elements.upload.classList.toggle('good', stage >= 2);
    elements.uploadProgress.style.transform = `scaleX(${stage === 0 ? 0 : stage === 1 ? .62 : 1})`;
    elements.health.textContent = stage < 2 ? '—' : ['72','72','76','81','92'][stage - 2];
    elements.blockers.textContent = stage < 2 ? '—' : stage >= 4 ? '2' : '3';
    elements.alerts.textContent = stage < 2 ? '—' : stage >= 5 ? '9' : stage >= 3 ? '14' : '17';
    elements.alternates.textContent = stage < 3 ? '—' : stage === 3 ? '4' : '6';
    $$('.phase-track span').forEach((node, index) => node.classList.toggle('done', stage >= index + 1));
    $$('.side-item').forEach((node, index) => node.classList.toggle('active', index === Math.min(stage, 5)));
    $$('.evidence-strip div').forEach((node, index) => {
      const active = [stage >= 2, stage >= 2, stage >= 3, stage >= 3, stage >= 5][index];
      node.classList.toggle('resolved', active);
    });
    $$('.risk-row').forEach((node, index) => node.classList.toggle('revealed', stage >= 2 && index <= Math.max(0, stage - 2)));

    elements.qCaret.style.display = stage === 3 ? 'inline-block' : 'none';
    elements.thinking.classList.toggle('visible', stage === 3);
    elements.ai.classList.toggle('visible', stage >= 4);
    elements.actions.classList.toggle('visible', stage >= 5);
    elements.toast.classList.toggle('visible', stage >= 5);
    elements.confidence.textContent = stage >= 4 ? '93% confidence' : 'Evidence grounded';
    elements.life.textContent = stage >= 2 ? 'EOL notice matched' : 'Waiting';
    elements.supply.textContent = stage >= 3 ? 'Second source identified' : 'Waiting';
    elements.decision.textContent = stage >= 5 ? 'DR-1048 approved' : 'Pending';

    if (stage < 3) elements.question.textContent = 'Ask a production-readiness question…';
    if (stage === 3) typeText(elements.question, question, 22);
    if (stage >= 4) elements.question.textContent = question;
    elements.answer.textContent = '';
    if (stage >= 4) typeText(elements.answer, answer, 12, 120);
    $$('#sceneDots button').forEach((node, index) => node.classList.toggle('active', index === stage));
  }

  function schedule() {
    clearTimeout(timer);
    if (paused) return;
    timer = setTimeout(() => { renderStage((stage + 1) % 6); schedule(); }, durations[stage]);
  }

  for (let i = 0; i < 6; i += 1) {
    const dot = document.createElement('button');
    dot.type = 'button'; dot.setAttribute('aria-label', `Scene ${i + 1}`);
    dot.addEventListener('click', () => { renderStage(i); schedule(); });
    $('#sceneDots').appendChild(dot);
  }
  $('#prevScene').addEventListener('click', () => { renderStage((stage + 5) % 6); schedule(); });
  $('#nextScene').addEventListener('click', () => { renderStage((stage + 1) % 6); schedule(); });
  elements.theater.addEventListener('mouseenter', () => { paused = true; clearTimeout(timer); });
  elements.theater.addEventListener('mouseleave', () => { paused = false; schedule(); });
  renderStage(0); schedule();

  let pipelineStage = 0;
  const pipeline = $('#pipeline');
  const pArticles = $$('#pipeline article');
  function renderPipeline(index) {
    pipelineStage = index;
    const fill = $('.pipeline-line span');
    const file = $('.moving-file');
    fill.style.width = `${index * 25}%`;
    file.style.left = `calc(${index * 25}% + ${index === 0 ? '8%' : '8%'} - 19px)`;
    pArticles.forEach((article, i) => {
      article.classList.toggle('active', i === index);
      article.classList.toggle('done', i < index);
      article.querySelector('i').textContent = i < index ? '✓' : String(i + 1);
    });
  }
  pArticles.forEach((article, index) => article.addEventListener('mouseenter', () => renderPipeline(index)));
  setInterval(() => renderPipeline((pipelineStage + 1) % 5), 1800);
  renderPipeline(0);

  const story = $('#copilotStory');
  let storyPlayed = false;
  const observer = new IntersectionObserver(([entry]) => {
    if (!entry.isIntersecting || storyPlayed) return;
    storyPlayed = true;
    $$('.source-list div').forEach((node, index) => setTimeout(() => node.classList.add('active'), 800 + index * 420));
    typeText($('#storyQuestion'), question, 25, 250);
    typeText($('#storyAnswer'), answer, 13, 2500);
  }, { threshold: .35 });
  observer.observe(story);

  const supplierNodes = $$('.supplier-node');
  const supplierRows = $$('.supplier-table button');
  function selectSupplier(index) {
    supplierNodes.forEach((node, i) => node.classList.toggle('active', i === index));
    supplierRows.forEach((row, i) => row.classList.toggle('selected', i === index));
  }
  supplierNodes.forEach((node, index) => node.addEventListener('click', () => selectSupplier(index)));
  supplierRows.forEach((row, index) => row.addEventListener('click', () => selectSupplier(index)));

  $('#approveDecision').addEventListener('click', () => {
    const record = $('#decisionRecord');
    record.classList.add('approved');
    $('#approveDecision').textContent = '✓ Approved';
    $('#recordStatus').textContent = 'APPROVED';
    const items = $$('.approval-track i');
    const labels = $$('.approval-track span');
    items.forEach((item) => item.classList.add('done'));
    labels[2].textContent = 'Decision approved'; labels[3].textContent = 'Monitoring active';
  });
})();

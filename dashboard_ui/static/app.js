(function () {
  const DEFAULT_MAX_SCORE = 47;

  /** Returns the current URL pathname. */
  function getPath() {
    return window.location.pathname;
  }

  /**
   * Parse the pathname to detect a /transcript/:group/:version URL.
   * @returns {{group: string, version: string}|null}
   */
  function isTranscriptPage() {
    const m = getPath().match(/^\/transcript\/([^/]+)\/([^/]+)\/?$/);
    return m ? { group: m[1], version: m[2] } : null;
  }

  /** Hide all .page elements and show the one with the given id. */
  function showPage(id) {
    document.querySelectorAll("#main .page").forEach((p) => p.classList.add("hidden"));
    const el = document.getElementById(id);
    if (el) el.classList.remove("hidden");
  }

  /**
   * Build a label array [0, 1, ..., maxScore] for chart x-axis.
   * @param {number} maxScore
   */
  function scoreLabels(maxScore) {
    const labels = [];
    for (let s = 0; s <= maxScore; s++) labels.push(s);
    return labels;
  }

  /**
   * Count occurrences of each integer score in [0..maxScore]; null/undefined entries are skipped.
   * @param {(number|null|undefined)[]} scores
   * @param {number} maxScore
   * @returns {number[]}
   */
  function histogram(scores, maxScore) {
    const counts = [];
    for (let i = 0; i <= maxScore; i++) counts[i] = 0;
    scores.filter((s) => s != null).forEach((s) => {
      if (s >= 0 && s <= maxScore) counts[s] = (counts[s] || 0) + 1;
    });
    return counts;
  }

  /**
   * Render or replace a Chart.js bar chart on the given canvas showing score distribution.
   * Destroys any existing chart instance stored on window[canvasId + "Chart"] before redrawing.
   * @param {string} canvasId - DOM id of the <canvas> element
   * @param {number[]} scores - raw score values to histogram
   * @param {string} label - dataset label prefix
   * @param {string} color - bar fill/border color
   * @param {number} maxScore - upper bound of the x-axis
   */
  function drawChart(canvasId, scores, label, color, maxScore) {
    const counts = histogram(scores, maxScore);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (window[canvasId + "Chart"]) window[canvasId + "Chart"].destroy();
    window[canvasId + "Chart"] = new Chart(ctx, {
      type: "bar",
      data: {
        labels: scoreLabels(maxScore),
        datasets: [
          {
            label: label + " conversations",
            data: counts,
            backgroundColor: color,
            borderColor: color,
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            title: { display: true, text: "Score" },
            grid: { display: false },
            min: 0,
            max: maxScore,
            ticks: { stepSize: 1 },
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: "Count" },
            ticks: { stepSize: 1 },
          },
        },
      },
    });
  }

  /**
   * Infer the maximum score from gpt_max/claude_max fields across the row list;
   * falls back to DEFAULT_MAX_SCORE when no finite values are present.
   * @param {object[]} list
   * @returns {number}
   */
  function inferMaxScore(list) {
    const maxes = list
      .flatMap((t) => [t.gpt_max, t.claude_max])
      .filter((v) => typeof v === "number" && Number.isFinite(v));
    if (!maxes.length) return DEFAULT_MAX_SCORE;
    return Math.max(...maxes);
  }

  /**
   * Parse x as an integer; returns Infinity for non-numeric values (used for sort ordering
   * so that missing/non-numeric entries sort to the end).
   * @param {*} x
   * @returns {number}
   */
  function parseNumericOrInfinity(x) {
    const n = Number.parseInt(String(x || ""), 10);
    return Number.isFinite(n) ? n : Number.POSITIVE_INFINITY;
  }

  /**
   * Render the full dashboard: score charts + sortable transcript table.
   * Sets up column-header click handlers for client-side sorting.
   * @param {object[]} list - combined transcript and bundle row objects
   */
  function renderDashboard(list) {
    const maxScore = inferMaxScore(list);
    const gptScores = list.map((t) => t.gpt_score).filter((s) => s != null);
    const claudeScores = list.map((t) => t.claude_score).filter((s) => s != null);
    drawChart("chart-gpt", gptScores, "GPT", "#a65dea", maxScore);
    drawChart("chart-claude", claudeScores, "Claude", "#ff893a", maxScore);

    let sortKey = "group";
    let sortDir = 1;

    /**
     * Return the display label for a row's group column:
     * student_persona for individual transcripts, group name for bundle rows.
     * @param {object} t
     * @returns {string}
     */
    function displayedGroup(t) {
      if (t.kind === "transcript") {
        return String((t.metadata && t.metadata.student_persona) || t.group || "");
      }
      return String(t.group || "");
    }

    /**
     * Re-sort and re-render the transcript table body according to current sortKey/sortDir.
     * Numeric columns (score, version, exercise) fall back to string compare when equal.
     */
    function renderTable() {
      const sorted = [...list].sort((a, b) => {
        if (sortKey === "group") {
          const groupCompare = displayedGroup(a).localeCompare(displayedGroup(b));
          if (groupCompare !== 0) return sortDir * groupCompare;
          const versionCompare = parseNumericOrInfinity(a.version) - parseNumericOrInfinity(b.version);
          if (versionCompare !== 0) return sortDir * versionCompare;
          const courseCompare = String((a.metadata && a.metadata.course) || "").localeCompare(
            String((b.metadata && b.metadata.course) || "")
          );
          if (courseCompare !== 0) return sortDir * courseCompare;
          return sortDir * (
            parseNumericOrInfinity(a.metadata && a.metadata.exercise_number) -
            parseNumericOrInfinity(b.metadata && b.metadata.exercise_number)
          );
        }
        if (sortKey === "version") {
          const aNum = parseNumericOrInfinity(a.version);
          const bNum = parseNumericOrInfinity(b.version);
          if (aNum !== bNum) return sortDir * (aNum - bNum);
          return sortDir * String(a.version || "").localeCompare(String(b.version || ""));
        }
        if (sortKey === "course") {
          return sortDir * String((a.metadata && a.metadata.course) || "").localeCompare(
            String((b.metadata && b.metadata.course) || "")
          );
        }
        if (sortKey === "exercise") {
          const aEx = String((a.metadata && a.metadata.exercise_number) || "");
          const bEx = String((b.metadata && b.metadata.exercise_number) || "");
          const aNum = Number.parseInt(aEx, 10);
          const bNum = Number.parseInt(bEx, 10);
          if (Number.isFinite(aNum) && Number.isFinite(bNum) && aNum !== bNum) {
            return sortDir * (aNum - bNum);
          }
          return sortDir * aEx.localeCompare(bEx);
        }
        const va = a[sortKey];
        const vb = b[sortKey];
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === "number" && typeof vb === "number") return sortDir * (va - vb);
        return sortDir * String(va).localeCompare(String(vb));
      });

      const tbody = document.getElementById("transcripts-tbody");
      tbody.innerHTML = sorted
        .map(
          (t) =>
            `<tr>
          <td>${escapeHtml(displayedGroup(t) || "—")}</td>
          <td>${escapeHtml(t.version || "—")}</td>
          <td>${escapeHtml((t.metadata && t.metadata.course) || "—")}</td>
          <td>${escapeHtml((t.metadata && t.metadata.exercise_number) || "—")}</td>
          <td class="num"><span class="score-cell">${t.gpt_score != null ? t.gpt_score + "/" + (t.gpt_max != null ? t.gpt_max : maxScore) : "—"}</span></td>
          <td class="num"><span class="score-cell">${t.claude_score != null ? t.claude_score + "/" + (t.claude_max != null ? t.claude_max : maxScore) : "—"}</span></td>
          <td><a href="/transcript/${encodeURIComponent(t.route_group || t.group)}/${encodeURIComponent(t.route_version || t.version)}">Read</a></td>
        </tr>`
        )
        .join("");
    }

    document.querySelectorAll("#transcripts-table thead th[data-sort]").forEach((th) => {
      th.classList.remove("sorted-asc", "sorted-desc");
      th.onclick = () => {
        const key = th.getAttribute("data-sort");
        if (sortKey === key) sortDir *= -1;
        else sortDir = key === "gpt_score" || key === "claude_score" ? -1 : 1;
        sortKey = key;
        document.querySelectorAll("#transcripts-table thead th[data-sort]").forEach((h) => h.classList.remove("sorted-asc", "sorted-desc"));
        th.classList.add(sortDir === 1 ? "sorted-asc" : "sorted-desc");
        renderTable();
      };
    });
    const groupTh = document.querySelector('#transcripts-table thead th[data-sort="group"]');
    if (groupTh) groupTh.classList.add("sorted-asc");
    renderTable();
  }

  /**
   * Safely escape a string for insertion into innerHTML.
   * Uses a temporary DOM element so the browser handles all entity encoding.
   * @param {*} s
   * @returns {string}
   */
  function escapeHtml(s) {
    if (s == null) return "";
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

  /**
   * Render an evaluator's grade panel (score, overview bullets, section criteria, deductions)
   * into container. Shows an error message when grade is absent.
   * @param {HTMLElement} container - element to populate
   * @param {object|null} grade - grade summary object from the API
   * @param {string} evaluatorLabel - display name (e.g. "GPT evaluator")
   * @param {string} cssClass - CSS class applied to container (e.g. "gpt" or "claude")
   * @param {string|null} errorMessage - shown instead of the default when grade is null
   */
  function renderGradeReport(container, grade, evaluatorLabel, cssClass, errorMessage) {
    if (!grade) {
      const message = errorMessage || `No ${evaluatorLabel} grade available.`;
      container.innerHTML = `<p class="error">${escapeHtml(message)}</p>`;
      return;
    }
    const overviewLines = Array.isArray(grade.overview)
      ? grade.overview
      : (typeof grade.overview === "string" && grade.overview.trim() ? [grade.overview] : []);
    const sections = grade.sections && typeof grade.sections === "object" ? grade.sections : {};
    const model = grade.model ? grade.model.provider + " / " + grade.model.model : "";
    let html =
      "<h3>\n        " +
      escapeHtml(evaluatorLabel) +
      '\n        <span class="total-score">' +
      grade.total_score +
      "/" +
      grade.max_score +
      "</span>\n      </h3>\n      " +
      (model ? '<p style="font-size:0.8rem;color:var(--text-muted);margin:-0.5rem 0 0.5rem">' + escapeHtml(model) + "</p>" : "");
    if (overviewLines.length) {
      html += '<div class="overview"><ul>';
      overviewLines.forEach((line) => {
        html += "<li>" + escapeHtml(line) + "</li>";
      });
      html += "</ul></div>";
    }
    if (Object.keys(sections).length) {
      html += '<div class="sections">';
      for (const [secId, sec] of Object.entries(sections)) {
        if (!sec.criteria) continue;
        html += '<div class="section-block"><h4>' + escapeHtml(secId) + "</h4>";
        for (const c of Object.values(sec.criteria)) {
          html += '<div class="criterion">';
          html += '<span class="name">' + escapeHtml(c.name) + "</span>";
          html += '<span class="score">' + c.score + "/" + c.max + "</span>";
          html += "</div>";
          if (c.deductions && c.deductions.length) {
            c.deductions.forEach((d) => {
              const subsectionId = d.sub_criterion_id || d.criterion_id || d.id || "unknown";
              html +=
                '<div class="deduction">[' +
                escapeHtml(subsectionId) +
                "] −" +
                d.points +
                ": " +
                escapeHtml(d.reason) +
                "</div>";
            });
          }
        }
        if (sec.bonus && sec.bonus.score != null && sec.bonus.score > 0) {
          html += '<div class="criterion"><span class="name">Bonus: ' + escapeHtml(sec.bonus.id || "bonus") + '</span><span class="score">+' + sec.bonus.score + "</span></div>";
          if (sec.bonus.explanation) html += '<div class="deduction" style="color:var(--score-high)">' + escapeHtml(sec.bonus.explanation) + "</div>";
        }
        if (sec.malus && sec.malus.score != null && sec.malus.score > 0) {
          html += '<div class="criterion"><span class="name">Malus: ' + escapeHtml(sec.malus.id || "malus") + '</span><span class="score">-' + sec.malus.score + "</span></div>";
          if (sec.malus.explanation) html += '<div class="deduction">' + escapeHtml(sec.malus.explanation) + "</div>";
        }
        html += "</div>";
      }
      html += "</div>";
    }
    container.className = "grade-report " + cssClass;
    container.innerHTML = html;
  }

  /**
   * Render the full transcript detail view: metadata header, raw bundle text or turn-by-turn
   * exchanges, and both GPT and Claude grade panels appended to #transcript-content.
   * @param {object} data - transcript detail object returned by /api/transcripts/:group/:version
   */
  function renderTranscript(data) {
    const meta = data.metadata || {};
    let html = '<div class="meta-top">';
    html += '<span><strong>Tutor prompt:</strong> ' + escapeHtml(meta.tutor_prompt || "—") + "</span>";
    html += '<span><strong>Student persona:</strong> ' + escapeHtml(meta.student_persona || "—") + "</span>";
    html += '<span><strong>Course:</strong> ' + escapeHtml(meta.course || "—") + "</span>";
    html += '<span><strong>Exercise:</strong> ' + escapeHtml(meta.exercise_number || "—") + "</span>";
    html += '<span><strong>Turns:</strong> ' + escapeHtml(String(meta.turns != null ? meta.turns : "—")) + "</span>";
    html += "</div>";

    if (data.raw_text) {
      html += '<details class="meta-block"><summary>Raw Bundle File</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(data.raw_text) + "</pre></details>";
    }
    if (meta.context) {
      html += '<details class="meta-block"><summary>Context</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(meta.context) + "</pre></details>";
    }
    if (meta.exercise) {
      html += '<details class="meta-block"><summary>Exercise</summary><pre style="white-space:pre-wrap;font-size:0.85rem;margin:0.5rem 0 0">' + escapeHtml(meta.exercise) + "</pre></details>";
    }

    (data.exchanges || []).forEach((ex) => {
      html += '<div class="exchange">';
      html += '<div class="turn-badge">Turn ' + ex.turn + "</div>";
      html += '<div class="student"><strong>Student:</strong><br/>' + escapeHtml(ex.student || "") + "</div>";
      html += '<div class="tutor"><strong>Tutor:</strong><br/>' + escapeHtml(ex.tutor || "") + "</div>";
      if (ex.pedagogical_reasoning) {
        html += '<div class="reasoning"><strong>Pedagogical reasoning:</strong><br/>' + escapeHtml(ex.pedagogical_reasoning) + "</div>";
      }
      html += "</div>";
    });

    const gptEl = document.createElement("div");
    const claudeEl = document.createElement("div");
    renderGradeReport(gptEl, data.grade_gpt, "GPT evaluator", "gpt", data.gpt_error);
    renderGradeReport(claudeEl, data.grade_claude, "Claude evaluator", "claude", data.claude_error);

    document.getElementById("transcript-title").textContent = `${data.group} / ${data.version}`;
    const content = document.getElementById("transcript-content");
    content.innerHTML = html;
    content.appendChild(gptEl);
    content.appendChild(claudeEl);
  }

  /**
   * Fetch all dashboard rows from /api/transcripts and render the dashboard page.
   * Shows a loading placeholder while the request is in flight, and an error row on failure.
   */
  async function loadDashboard() {
    showPage("dashboard-page");
    const tbody = document.getElementById("transcripts-tbody");
    tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading...</td></tr>';
    try {
      const r = await fetch("/api/transcripts");
      const list = await r.json();
      if (!r.ok) throw new Error(list.error || "Failed to load");
      if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="error">No transcript rows found.</td></tr>';
        return;
      }
      renderDashboard(list);
    } catch (e) {
      console.error("Failed to load transcripts:", e);
      tbody.innerHTML = '<tr><td colspan="7" class="error">' + escapeHtml(e.message) + "</td></tr>";
    }
  }

  /**
   * Fetch a single transcript detail from /api/transcripts/:group/:version and render it.
   * Shows a loading placeholder while the request is in flight.
   * @param {string} group
   * @param {string} version
   */
  async function loadTranscript(group, version) {
    showPage("transcript-page");
    const content = document.getElementById("transcript-content");
    content.innerHTML = '<p class="loading">Loading transcript...</p>';
    try {
      const r = await fetch("/api/transcripts/" + encodeURIComponent(group) + "/" + encodeURIComponent(version));
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Not found");
      renderTranscript(data);
    } catch (e) {
      content.innerHTML = '<p class="error">' + escapeHtml(e.message) + "</p>";
    }
  }

  /**
   * Decide which page to render based on the current URL: transcript detail or dashboard.
   * Called on initial load and on every popstate event.
   */
  function route() {
    const transcript = isTranscriptPage();
    if (transcript) {
      loadTranscript(transcript.group, transcript.version);
    } else {
      loadDashboard();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", route);
  } else {
    route();
  }

  window.addEventListener("popstate", route);
})();

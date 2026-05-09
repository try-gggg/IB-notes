function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderSummary(summary) {
  return `
    <h2>Quick Overview</h2>
    <div class="quick-facts">
      <div class="quick-fact"><strong>${summary.subjects}</strong>Subjects</div>
      <div class="quick-fact"><strong>${summary.notes}</strong>Rendered notes</div>
      <div class="quick-fact"><strong>${summary.pdfs}</strong>PDF references</div>
    </div>
  `;
}

function renderSubjectCards(subjects) {
  const cards = subjects
    .map(
      (subject) => `
        <section class="subject-card">
          <h3><a href="${subject.href}">${escapeHtml(subject.title)}</a></h3>
          <div class="subject-meta">
            <span class="subject-badge">${subject.note_count} notes</span>
            <span class="subject-badge">${subject.pdf_count} PDFs</span>
          </div>
          <div class="subject-actions">
            <a href="${subject.href}">Open subject</a>
          </div>
        </section>
      `
    )
    .join("");

  return `<div class="subject-grid">${cards}</div>`;
}

function renderBrowseCatalog(subjects) {
  return subjects
    .map((subject) => {
      const notes = subject.notes.length
        ? `
          <h3>Notes</h3>
          <ul class="catalog-list">
            ${subject.notes
              .map((note) => `<li><a href="${note.href}">${escapeHtml(note.title)}</a></li>`)
              .join("")}
          </ul>
        `
        : "";

      const pdfs = subject.pdfs.length
        ? `
          <h3>PDFs</h3>
          <ul class="catalog-list">
            ${subject.pdfs
              .map((pdf) => `<li><a href="${pdf.href}">${escapeHtml(pdf.title)}</a></li>`)
              .join("")}
          </ul>
        `
        : "";

      return `
        <section class="catalog-section">
          <h2 class="catalog-heading"><a href="${subject.href}">${escapeHtml(subject.title)}</a></h2>
          <p>${subject.note_count} notes • ${subject.pdf_count} PDFs</p>
          ${notes}
          ${pdfs}
        </section>
      `;
    })
    .join("");
}

async function loadSiteData() {
  const response = await fetch("generated/site-data.json");
  if (!response.ok) {
    throw new Error(`Failed to load site data: ${response.status}`);
  }
  return response.json();
}

function mount(selector, html) {
  const node = document.querySelector(selector);
  if (node) {
    node.innerHTML = html;
  }
}

async function main() {
  try {
    const data = await loadSiteData();
    mount("#home-summary", renderSummary(data.summary));
    mount("#subject-cards", renderSubjectCards(data.subjects));
    mount("#browse-catalog", renderBrowseCatalog(data.subjects));
  } catch (error) {
    const message = `<p>Site navigation data could not be loaded yet. Please rebuild the site.</p>`;
    mount("#home-summary", message);
    mount("#subject-cards", "");
    mount("#browse-catalog", message);
    console.error(error);
  }
}

main();

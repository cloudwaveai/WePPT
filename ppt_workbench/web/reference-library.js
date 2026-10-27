"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const state = {catalog: null};
  const project = new URLSearchParams(location.search).get("project");
  if (project) for (const id of ["home-link", "workbench-link", "guide-link"]) {
    const link = $(id);
    const url = new URL(link.href);
    url.searchParams.set("project", project);
    link.href = url.pathname + url.search;
  }
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  }
  const size = bytes => `${(bytes / 1048576).toFixed(1)} MiB`;
  const previewUrl = template => `/reference-library/${template.preview}`;
  function addField(list, label, value) {
    if (!value) return;
    list.append(node("dt", label), node("dd", String(value)));
  }
  function showDetail(template) {
    $("detail-title").textContent = `${template.template_id} · ${template.name}`;
    $("detail-image").src = previewUrl(template);
    $("detail-image").alt = `${template.name}原始模板完整预览`;
    const fields = $("detail-fields");
    fields.replaceChildren();
    for (const [label, value] of [
      ["源目录分类", template.category], ["适用内容", template.usage],
      ["实际容量", template.capacity_label], ["固定项", template.fixed],
      ["原 POTX 可替换区域", template.editable], ["使用条件", template.fit_rule],
      ["原始来源", `${template.source_file} · 原第 ${template.source_page} 页`],
      ["POTX 位置", `${template.library_file} · 第 ${template.library_page} 页`],
      ["本机文件", `${state.catalog.local_source_directory}/${template.library_file}`],
      ["原目录状态", template.status],
      ["示例事实", template.source_claims_verified ? "源目录标注已核验" : "源目录标注未核验，使用时须替换并核验"],
      ["模板化修正", template.title_change_reason], ["可读性修正", template.repair_note],
      ["POTX SHA-256", template.template_file_sha256]
    ]) addField(fields, label, value);
    $("reference-detail").showModal();
  }
  function render() {
    const all = state.catalog.templates;
    const q = $("search").value.trim().toLowerCase();
    const filtered = all.filter(t => (!$("category").value || t.category === $("category").value)
      && (!$("source-file").value || t.library_file === $("source-file").value)
      && (!q || [t.template_id, t.name, t.category, t.usage, t.source_file, t.library_file, t.capacity_label].join(" ").toLowerCase().includes(q)));
    $("library-status").textContent = `显示 ${filtered.length} / ${all.length} 页原始 POTX 参考 · ${state.catalog.files.length} 个原文件 · ${state.catalog.category_count} 类。点击真实预览查看大图与约束。`;
    const grid = $("reference-grid");
    grid.replaceChildren();
    if (!filtered.length) grid.append(node("p", "没有匹配的参考页，请调整或清除筛选。", "empty"));
    for (const t of filtered) {
      const card = node("article", undefined, "reference-card");
      const button = node("button", undefined, "preview-button");
      button.type = "button";
      button.setAttribute("aria-label", `查看 ${t.template_id} ${t.name} 大图与约束`);
      const image = node("img");
      image.src = previewUrl(t);
      image.alt = `${t.template_id} ${t.name} · 原始 POTX 真实预览`;
      image.loading = "lazy";
      image.decoding = "async";
      image.addEventListener("error", () => {
        image.hidden = true;
        button.append(node("span", "此页预览加载失败，点击查看来源与约束。"));
      }, {once: true});
      button.append(image);
      button.addEventListener("click", () => showDetail(t));
      const body = node("div", undefined, "card-body");
      body.append(node("p", `${t.template_id} · ${t.category}`, "card-meta"), node("h2", t.name),
        node("p", t.usage), node("p", t.capacity_label, "capacity"),
        node("p", `${t.source_file} · 原第 ${t.source_page} 页`, "source"),
        node("p", `${t.library_file.split("/").pop()} · 第 ${t.library_page} 页`, "source"),
        node("p", "原始 POTX 参考 · 不可直接套用", "reference-label"));
      card.append(button, body);
      grid.append(card);
    }
  }
  async function load() {
    $("retry").hidden = true;
    $("library-status").textContent = "正在读取真实模板预览…";
    try {
      const response = await fetch("/reference-library/catalog.json", {credentials: "same-origin"});
      if (!response.ok) throw new Error(response.status === 401 ? "请先使用启动链接打开工作台，再访问参考库。" : "参考目录暂时无法读取，请重试。");
      state.catalog = await response.json();
      for (const id of ["category", "source-file"]) $(id).length = 1;
      for (const category of [...new Set(state.catalog.templates.map(t => t.category))]) $("category").append(new Option(category, category));
      for (const file of state.catalog.files) $("source-file").append(new Option(file.file.split("/").pop(), file.file));
      $("source-directory").textContent = state.catalog.local_source_directory;
      $("download-note").textContent = state.catalog.download_note;
      $("source-note").textContent = state.catalog.note;
      $("source-files").replaceChildren();
      for (const file of state.catalog.files) {
        const entry = node("article");
        entry.append(node("h3", file.file.split("/").pop()), node("p", `${file.page_count} 页 · ${size(file.bytes)} · 仅本地源文件，未打包下载`));
        entry.append(node("code", `${state.catalog.local_source_directory}/${file.file}`));
        const details = node("details");
        details.append(node("summary", "原文件 SHA-256"), node("code", file.sha256));
        entry.append(details);
        $("source-files").append(entry);
      }
      render();
    } catch (error) {
      $("library-status").textContent = error.message;
      $("retry").hidden = false;
    }
  }
  $("search").addEventListener("input", () => { if (state.catalog) render(); });
  for (const id of ["category", "source-file"]) $(id).addEventListener("change", () => { if (state.catalog) render(); });
  $("reset").addEventListener("click", () => {
    for (const id of ["search", "category", "source-file"]) $(id).value = "";
    if (state.catalog) render();
  });
  $("retry").addEventListener("click", load);
  $("close-detail").addEventListener("click", () => $("reference-detail").close());
  load();
})();

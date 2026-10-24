"use strict";

// Keep every screen readable without JavaScript; enhance the overview into keyboard tabs.
document.querySelectorAll("[data-gallery]").forEach((gallery) => {
  const tablist = gallery.querySelector(".screen-tabs");
  const tabs = [...gallery.querySelectorAll("[data-screen]")];
  const panels = [...gallery.querySelectorAll("[data-panel]")];
  if (!tablist || tabs.length !== panels.length) return;
  tablist.setAttribute("role", "tablist");
  const select = (selected) => {
    tabs.forEach((tab, index) => {
      const active = index === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      panels[index].hidden = !active;
    });
  };
  tabs.forEach((tab, index) => {
    tab.id = `tab-${panels[index].id}`;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", panels[index].id);
    panels[index].setAttribute("role", "tabpanel");
    panels[index].setAttribute("aria-labelledby", tab.id);
    panels[index].tabIndex = 0;
    tab.addEventListener("click", (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
        return;
      event.preventDefault();
      select(index);
      history.replaceState(null, "", tab.hash);
      window.dispatchEvent(new Event("hashchange"));
    });
    tab.addEventListener("keydown", (event) => {
      let next;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      else if (event.key === "ArrowLeft")
        next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = tabs.length - 1;
      else return;
      event.preventDefault();
      tabs[next].click();
      tabs[next].focus();
    });
  });
  const fromHash = () => {
    const current = tabs.findIndex((tab) => tab.hash === location.hash);
    if (current >= 0) select(current);
  };
  select(0);
  fromHash();
  window.addEventListener("hashchange", fromHash);
});

const viewer = document.querySelector(".lightbox");
if (viewer && typeof viewer.showModal === "function") {
  const image = viewer.querySelector("img");
  const caption = viewer.querySelector(".lightbox-caption");
  let opener;
  document.querySelectorAll("[data-preview]").forEach((link) => {
    link.addEventListener("click", (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
        return;
      const original = link.querySelector("img");
      if (!original) return;
      event.preventDefault();
      opener = link;
      image.src = link.href;
      image.alt = original.alt;
      image.width = original.naturalWidth;
      image.height = original.naturalHeight;
      caption.textContent = original.alt;
      viewer.showModal();
    });
  });
  viewer.addEventListener("click", (event) => {
    if (event.target === viewer) {
      const rect = viewer.getBoundingClientRect();
      if (
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom
      )
        viewer.close();
    }
  });
  viewer.addEventListener("close", () =>
    opener?.focus({ preventScroll: true }),
  );
}

const languages = document.querySelector(".language-picker");
if (languages) {
  // Ordinary links work without JavaScript; preserve the tutorial section when switching.
  const keepSection = () => {
    languages.querySelectorAll("a[hreflang]").forEach((link) => {
      const target = new URL(link.href);
      target.hash = window.location.hash;
      link.href = target.href;
    });
  };
  keepSection();
  window.addEventListener("hashchange", keepSection);
  document.addEventListener("click", (event) => {
    if (event.target instanceof Node && !languages.contains(event.target))
      languages.open = false;
  });
  languages.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && languages.open) {
      event.preventDefault();
      languages.open = false;
      languages.querySelector("summary").focus();
    }
  });
}

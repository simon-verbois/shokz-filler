"use strict";

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

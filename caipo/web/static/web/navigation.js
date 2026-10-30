// Collapses the primary navigation behind a menu button on narrow screens.
// The button is made here: without this script there is no button, and the
// navigation is shown in full.
(function () {
  "use strict";
  var nav = document.getElementById("primary-nav");
  if (!nav) {
    return;
  }
  var toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "nav-toggle button--ghost button--small";
  toggle.textContent = nav.getAttribute("data-menu-label") || "Menu";
  toggle.setAttribute("aria-controls", "primary-nav");
  toggle.setAttribute("aria-expanded", "false");
  nav.parentNode.insertBefore(toggle, nav);
  nav.classList.add("is-collapsible");

  function close() {
    nav.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
  }

  toggle.addEventListener("click", function () {
    var open = nav.classList.toggle("is-open");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && nav.classList.contains("is-open")) {
      close();
      toggle.focus();
    }
  });
})();

document.addEventListener("click", function (e) {
  var toggle = e.target.closest("[data-menu-toggle]");
  if (toggle) {
    var menu = document.querySelector("[data-menu]");
    if (menu) menu.classList.toggle("is-open");
    toggle.classList.toggle("is-active");
    return;
  }
  var link = e.target.closest("[data-menu] a");
  if (link) {
    var openMenu = document.querySelector("[data-menu].is-open");
    var openToggle = document.querySelector("[data-menu-toggle].is-active");
    if (openMenu) openMenu.classList.remove("is-open");
    if (openToggle) openToggle.classList.remove("is-active");
  }
});

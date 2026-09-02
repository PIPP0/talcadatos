(function () {
  var track = document.querySelector("[data-hero-track]");
  if (!track) return;

  var slides = track.children;
  var total = slides.length;
  var dots = document.querySelectorAll("[data-hero-dot]");
  var prevBtn = document.querySelector("[data-hero-prev]");
  var nextBtn = document.querySelector("[data-hero-next]");
  var index = 0;
  var timer = null;
  var AUTOPLAY_MS = 5000;

  function render() {
    track.style.transform = "translateX(-" + (index * (100 / total)) + "%)";
    dots.forEach(function (dot, i) {
      dot.classList.toggle("is-active", i === index);
    });
  }

  function goTo(i) {
    index = (i + total) % total;
    render();
  }

  function next() {
    goTo(index + 1);
  }

  function prev() {
    goTo(index - 1);
  }

  function restartAutoplay() {
    if (timer) clearInterval(timer);
    timer = setInterval(next, AUTOPLAY_MS);
  }

  if (nextBtn) {
    nextBtn.addEventListener("click", function () {
      next();
      restartAutoplay();
    });
  }
  if (prevBtn) {
    prevBtn.addEventListener("click", function () {
      prev();
      restartAutoplay();
    });
  }
  dots.forEach(function (dot) {
    dot.addEventListener("click", function () {
      goTo(parseInt(dot.getAttribute("data-hero-dot"), 10));
      restartAutoplay();
    });
  });

  render();
  restartAutoplay();
})();

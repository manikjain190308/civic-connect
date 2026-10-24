// CivicConnect front-end behaviour
document.addEventListener("DOMContentLoaded", () => {
  // Animated counters on the public dashboard
  document.querySelectorAll("[data-count]").forEach((el) => {
    const target = parseInt(el.dataset.count, 10) || 0;
    if (target === 0) return;
    const steps = 30;
    let i = 0;
    const timer = setInterval(() => {
      i++;
      el.textContent = Math.round((target * i) / steps);
      if (i >= steps) clearInterval(timer);
    }, 25);
  });

  // Photo preview on the report form
  const photo = document.getElementById("photo");
  const preview = document.getElementById("preview");
  if (photo && preview) {
    photo.addEventListener("change", () => {
      const file = photo.files && photo.files[0];
      if (!file) { preview.style.display = "none"; return; }
      if (file.size > 6 * 1024 * 1024) {
        alert("Photo is larger than 6 MB. Please choose a smaller one.");
        photo.value = "";
        preview.style.display = "none";
        return;
      }
      preview.src = URL.createObjectURL(file);
      preview.style.display = "block";
    });
  }

  // "Use my current location" button
  const btn = document.getElementById("locBtn");
  const status = document.getElementById("locStatus");
  if (btn) {
    btn.addEventListener("click", () => {
      if (!navigator.geolocation) { status.textContent = "Location is not supported on this device."; return; }
      status.textContent = "Detecting location…";
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          document.getElementById("latitude").value = pos.coords.latitude.toFixed(7);
          document.getElementById("longitude").value = pos.coords.longitude.toFixed(7);
          status.textContent = "✅ Location captured (" +
            pos.coords.latitude.toFixed(4) + ", " + pos.coords.longitude.toFixed(4) + ")";
        },
        () => { status.textContent = "Could not get location. Enter the address manually; a photo with GPS data also works."; },
        { enableHighAccuracy: true, timeout: 10000 }
      );
    });
  }
});

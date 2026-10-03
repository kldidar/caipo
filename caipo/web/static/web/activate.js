// Moves the activation code from the part of the address after "#" into the
// form, and removes it from the address bar and the history entry. A browser
// never sends that part to a server, so the code reaches the server only in
// the body of the form, by POST.
(function () {
  "use strict";
  var field = document.getElementById("id_token");
  var code = window.location.hash.slice(1);
  if (field && code) {
    field.value = code;
    window.history.replaceState(null, "", window.location.pathname);
  }
})();

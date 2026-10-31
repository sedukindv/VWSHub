(() => {
  "use strict";
  document
    .querySelectorAll("[data-icon]")
    .forEach(
      (node) => (node.innerHTML = window.VWSIcons.html(node.dataset.icon)),
    );
  if (
    document.body.dataset.faviconIcon &&
    document.body.dataset.hasFavicon !== "yes"
  ) {
    const link = document.createElement("link");
    link.rel = "icon";
    link.href = window.VWSIcons.dataURL(
      document.body.dataset.faviconIcon,
      getComputedStyle(document.body).getPropertyValue("--accent").trim(),
    );
    document.head.append(link);
  }
  const en = {
    authHero: "Everything in view.<br><span>Even the past.</span>",
    authIntro:
      "Live video, XMEye recorder archives and device management in one workspace.",
    authLive: "An operator workspace",
    authLiveSub: "Layouts, spaces and quick camera access",
    authArchive: "Archive directly from your recorder",
    authArchiveSub: "No duplicate server recordings",
    authAccess: "Access to cameras, spaces and zones",
    authAccessSub: "Give each user the cameras they need",
    loginTitle: "Sign in",
    loginIntro: "Open your video workspace.",
    login: "Login",
    password: "Password",
    signIn: "Sign in",
    setupHero: "Your workspace.<br><span>Your rules.</span>",
    setupAbout:
      "Create an administrator, connect devices and assign camera access. There are no default accounts or passwords.",
    firstRun: "FIRST START",
    setupTitle: "Create an administrator",
    setupIntro:
      "This page is available only until the first account is created.",
    alias: "Display name",
    passwordHint: "At least 10 characters.",
    confirmPassword: "Confirm password",
    createAdmin: "Create administrator",
  };
  const nodes = [...document.querySelectorAll("[data-i18n]")];
  nodes.forEach((n) => (n.dataset.ru = n.innerHTML));
  const lang = document.querySelector("#auth-language");
  const apply = (value) => {
    nodes.forEach(
      (n) =>
        (n.innerHTML =
          value === "en" ? en[n.dataset.i18n] || n.dataset.ru : n.dataset.ru),
    );
    try {
      localStorage.setItem("vwshub.language", value);
    } catch (_) {}
    document.documentElement.lang = value;
  };
  if (lang) {
    let initial = "ru";
    try {
      initial = localStorage.getItem("vwshub.language") || "ru";
    } catch (_) {}
    lang.value = initial;
    apply(initial);
    lang.onchange = () => apply(lang.value);
  }
  const pw = document.querySelector("#password"),
    confirm = document.querySelector("#password-confirm");
  if (confirm) {
    const sync = () =>
      confirm.setCustomValidity(
        pw.value === confirm.value
          ? ""
          : lang?.value === "en"
            ? "Passwords do not match"
            : "Пароли не совпадают",
      );
    pw.addEventListener("input", sync);
    confirm.addEventListener("input", sync);
  }
})();

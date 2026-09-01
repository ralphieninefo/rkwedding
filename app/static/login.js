const form = document.querySelector("#loginForm");
const message = document.querySelector("#loginMessage");

const destination = () => {
  const requested = new URLSearchParams(window.location.search).get("next") || "/";
  return requested.startsWith("/") && !requested.startsWith("//") ? requested : "/";
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  button.textContent = "Signing in…";
  message.textContent = "";
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    const response = await fetch("/api/login", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(values),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || "Could not sign in.");
    window.location.assign(destination());
  } catch (error) {
    message.textContent = error instanceof Error ? error.message : "Could not sign in.";
    button.disabled = false;
    button.textContent = "Sign in";
  }
});

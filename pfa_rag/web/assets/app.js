import Keycloak from "/vendor/keycloak.js";

const lookup = (id) => document.getElementById(id);
const login = lookup("login");
const logout = lookup("logout");
const searchForm = lookup("search");
const status = lookup("status");
const identity = lookup("identity");
const results = lookup("results");
const sources = lookup("sources");
const documentPanel = lookup("document");
const redirectUri = location.origin + "/";
let keycloak;

function clearResults() {
  lookup("answer").hidden = true;
  lookup("answer-text").textContent = "";
  results.hidden = true;
  documentPanel.hidden = true;
  sources.replaceChildren();
  lookup("document-title").textContent = "";
  lookup("document-text").textContent = "";
}

async function api(path, options = {}) {
  await keycloak.updateToken(30);
  const response = await fetch(path, {
    ...options,
    cache: "no-store",
    headers: {
      "Authorization": "Bearer " + keycloak.token,
      "Content-Type": "application/json",
    },
  });
  if (response.status === 401) throw new Error("Votre session a expiré. Reconnectez-vous.");
  if (response.status === 403) throw new Error("Ce compte ne possède aucun rôle pour cette application.");
  if (response.status === 404) throw new Error("Cette source est indisponible.");
  if (!response.ok) throw new Error("La recherche est temporairement indisponible.");
  return await response.json();
}

async function showDocument(path) {
  documentPanel.hidden = true;
  try {
    const source = await api(path);
    lookup("document-title").textContent = source.title;
    lookup("document-text").textContent = source.text;
    documentPanel.hidden = false;
  } catch (error) {
    status.textContent = error.message;
  }
}

searchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearResults();
  const button = lookup("submit");
  button.disabled = true;
  status.textContent = "Recherche des sources et génération…";
  try {
    const answer = await api("/api/v1/answers", {
      method: "POST",
      body: JSON.stringify({question: lookup("question").value.trim(), strategy: lookup("strategy").value}),
    });
    lookup("answer-text").textContent = answer.answer;
    lookup("answer").hidden = false;
    for (const source of answer.citations) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "source";
      button.textContent = source.title;
      button.addEventListener("click", () => showDocument(source.url));
      const id = document.createElement("span");
      id.className = "source-id";
      id.textContent = source.document_id;
      item.append(button, id);
      sources.append(item);
    }
    results.hidden = answer.citations.length === 0;
    status.textContent = "";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

login.addEventListener("click", () => keycloak.login({redirectUri}));
logout.addEventListener("click", () => {
  clearResults();
  searchForm.hidden = true;
  identity.hidden = true;
  keycloak.logout({redirectUri});
});

async function start() {
  try {
    const response = await fetch("/api/config");
    if (!response.ok) throw new Error("Configuration indisponible.");
    const config = await response.json();
    const [url, realm] = config.issuer.split("/realms/");
    keycloak = new Keycloak({url, realm, clientId: config.client_id});
    const signedIn = await keycloak.init({pkceMethod: "S256", checkLoginIframe: false, redirectUri});
    login.hidden = signedIn;
    logout.hidden = !signedIn;
    if (!signedIn) {
      status.textContent = "Connectez-vous pour rechercher dans le corpus.";
      return;
    }
    const session = await api("/api/v1/me");
    identity.textContent = session.username + " · " + session.roles.join(", ");
    identity.hidden = false;
    searchForm.hidden = false;
    status.textContent = "";
  } catch (error) {
    status.textContent = error?.message || "Connexion à Keycloak indisponible.";
  }
}

start();

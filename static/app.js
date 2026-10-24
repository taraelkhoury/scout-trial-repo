const account = document.querySelector("#account");
const loginPanel = document.querySelector("#login-panel");
const productsElement = document.querySelector("#products");
const orderPanel = document.querySelector("#order-panel");
const ordersPanel = document.querySelector("#orders-panel");
const adminPanel = document.querySelector("#admin-panel");
const notice = document.querySelector("#notice");
const basket = new Map();
let currentUser = null;
let products = [];

function showNotice(message, isError = false) {
  notice.textContent = message;
  notice.classList.toggle("error", isError);
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}

function money(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

function button(label, action, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  if (className) element.className = className;
  element.addEventListener("click", action);
  return element;
}

function renderProducts() {
  productsElement.replaceChildren();
  for (const product of products) {
    const card = document.createElement("article");
    card.className = "product-card";
    const badge = document.createElement("span");
    badge.className = product.available ? "badge" : "badge unavailable";
    badge.textContent = product.available ? "In stock" : "Unavailable";
    const name = document.createElement("h3");
    name.textContent = product.name;
    const price = document.createElement("p");
    price.className = "price";
    price.textContent = money(product.price_cents);
    card.append(badge, name, price);
    if (currentUser && product.available) {
      const quantity = document.createElement("input");
      quantity.type = "number";
      quantity.min = "1";
      quantity.max = "20";
      quantity.value = basket.get(product.id) || "1";
      quantity.setAttribute("aria-label", `Quantity of ${product.name}`);
      quantity.addEventListener("change", () => {
        const value = Number.parseInt(quantity.value, 10);
        if (Number.isInteger(value) && value >= 1 && value <= 20) {
          basket.set(product.id, value);
          renderBasket();
        } else {
          quantity.value = basket.get(product.id) || 1;
        }
      });
      card.append(quantity, button("Add to basket", () => {
        basket.set(product.id, Number.parseInt(quantity.value, 10));
        renderBasket();
        showNotice(`${product.name} added to your basket.`);
      }, "secondary"));
    }
    productsElement.append(card);
  }
}

function renderBasket() {
  orderPanel.classList.toggle("hidden", !currentUser || basket.size === 0);
  if (!currentUser || basket.size === 0) return;
  const heading = orderPanel.querySelector("h2");
  const total = [...basket].reduce((sum, [id, quantity]) => {
    const product = products.find((item) => item.id === id);
    return sum + (product ? product.price_cents * quantity : 0);
  }, 0);
  heading.textContent = `Basket total: ${money(total)}`;
}

function renderAdminProducts() {
  const container = document.querySelector("#admin-products");
  container.replaceChildren();
  for (const product of products) {
    const form = document.createElement("form");
    form.className = "admin-row";
    const name = document.createElement("input");
    name.value = product.name;
    name.maxLength = 80;
    name.required = true;
    name.setAttribute("aria-label", `Name for ${product.name}`);
    const price = document.createElement("input");
    price.type = "number";
    price.min = "0.01";
    price.step = "0.01";
    price.value = (product.price_cents / 100).toFixed(2);
    price.required = true;
    price.setAttribute("aria-label", `Price for ${product.name}`);
    const availableLabel = document.createElement("label");
    availableLabel.className = "availability";
    const available = document.createElement("input");
    available.type = "checkbox";
    available.checked = product.available;
    availableLabel.append(available, document.createTextNode(" Available"));
    const save = document.createElement("button");
    save.type = "submit";
    save.textContent = "Save";
    form.append(name, price, availableLabel, save);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const priceCents = Math.round(Number(price.value) * 100);
        await api(`/api/admin/products/${product.id}`, {
          method: "POST",
          body: JSON.stringify({
            name: name.value,
            price_cents: priceCents,
            available: available.checked,
          }),
        });
        await loadProducts();
        showNotice("Product updated.");
      } catch (error) {
        showNotice(error.message, true);
      }
    });
    container.append(form);
  }
}

function renderAccount() {
  account.replaceChildren();
  if (!currentUser) {
    loginPanel.classList.remove("hidden");
    ordersPanel.classList.add("hidden");
    adminPanel.classList.add("hidden");
    return;
  }
  loginPanel.classList.add("hidden");
  const label = document.createElement("span");
  label.textContent = `${currentUser.username} (${currentUser.role})`;
  account.append(label, button("Sign out", async () => {
    try {
      await api("/api/logout", { method: "POST" });
      currentUser = null;
      basket.clear();
      renderAccount();
      renderProducts();
      renderBasket();
      showNotice("You have signed out.");
    } catch (error) {
      showNotice(error.message, true);
    }
  }, "secondary"));
  ordersPanel.classList.remove("hidden");
  adminPanel.classList.toggle("hidden", currentUser.role !== "admin");
}

async function loadProducts() {
  products = (await api("/api/products")).products;
  renderProducts();
  renderBasket();
  if (currentUser?.role === "admin") renderAdminProducts();
}

async function loadOrders() {
  if (!currentUser) return;
  const orders = (await api("/api/orders")).orders;
  const container = document.querySelector("#orders");
  const title = document.querySelector("#orders-title");
  title.textContent = currentUser.role === "admin" ? "All orders" : "Your orders";
  container.replaceChildren();
  if (orders.length === 0) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No orders yet.";
    container.append(empty);
    return;
  }
  for (const order of orders) {
    const card = document.createElement("article");
    card.className = "order-card";
    const title = document.createElement("h3");
    title.textContent = `Order #${order.id} · ${money(order.total_cents)}`;
    const details = document.createElement("p");
    details.textContent = `${order.items.map((item) =>
      `${item.quantity} × ${item.name} (${money(item.unit_price_cents)})`).join(", ")}${currentUser.role === "admin" ? ` · Customer: ${order.username}` : ""}`;
    const extra = document.createElement("p");
    extra.hidden = true;
    const view = button("View order details", async () => {
      try {
        const result = await api(`/api/orders/${order.id}`);
        extra.textContent = `Placed: ${result.order.created_at} | Customer: ${result.order.username} | ${result.order.items.map((item) => `${item.quantity} x ${item.name}`).join(", ")}`;
        extra.hidden = false;
      } catch (error) {
        showNotice(error.message, true);
      }
    }, "secondary");
    card.append(title, details, view, extra);
    container.append(card);
  }
}

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const loginForm = event.currentTarget;
  const form = new FormData(loginForm);
  try {
    const result = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({
        username: form.get("username"),
        password: form.get("password"),
      }),
    });
    currentUser = result.user;
    loginForm.reset();
    renderAccount();
    await loadProducts();
    await loadOrders();
    showNotice(`Welcome, ${currentUser.username}.`);
  } catch (error) {
    showNotice(error.message, true);
  }
});

document.querySelector("#place-order").addEventListener("click", async () => {
  try {
    const result = await api("/api/orders", {
      method: "POST",
      body: JSON.stringify({
        items: [...basket].map(([product_id, quantity]) => ({ product_id, quantity })),
      }),
    });
    basket.clear();
    await loadProducts();
    await loadOrders();
    showNotice(`Order #${result.order_id} placed.`);
  } catch (error) {
    showNotice(error.message, true);
  }
});

async function start() {
  try {
    currentUser = (await api("/api/me")).user;
    renderAccount();
    await loadProducts();
    if (currentUser) await loadOrders();
  } catch (error) {
    showNotice(error.message, true);
  }
}

start();

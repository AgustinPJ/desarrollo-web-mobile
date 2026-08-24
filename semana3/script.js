
const pizzas = [
  {
    nombre: "Margarita",
    precio: 8990,
    ingredientes: ["Tomate", "Mozzarella", "Albahaca"],
    destacada: false
  },
  {
    nombre: "Pepperoni",
    precio: 9990,
    ingredientes: ["Tomate", "Mozzarella", "Pepperoni"],
    destacada: true
  },
  {
    nombre: "Cuatro Quesos",
    precio: 10990,
    ingredientes: ["Mozzarella", "Parmesano", "Gorgonzola", "Provolone"],
    destacada: false
  }
];


function mostrarMenu() {
  const contenedor = document.querySelector("#menu-container");

  pizzas.forEach((pizza) => {
    const columna = document.createElement("div");
    columna.className = "col-12 col-md-4";

    const precioFormateado = pizza.precio.toLocaleString("es-CL");

    const badge = pizza.destacada
      ? `<span class="badge badge-destacada mb-2">Más pedida</span>`
      : "";

    columna.innerHTML = `
      <div class="card pizza-card">
        <div class="card-body">
          ${badge}
          <h3 class="card-title">${pizza.nombre}</h3>
          <p class="precio">$${precioFormateado}</p>
          <p class="ingredientes">${pizza.ingredientes.join(", ")}</p>
        </div>
      </div>
    `;

    contenedor.appendChild(columna);
  });
}

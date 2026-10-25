// La Tienda del Fuego: catálogo, filtros y pedido.
// Los productos llegan desde el servicio simulado (js/api.js)
// y se convierten en tarjetas con la API del DOM.

let productos = [];
let filtroActual = "Todos";

document.addEventListener("DOMContentLoaded", () => {
    configurarFecha();
    registrarEventos();
    cargarCatalogo();
});

// Formatea un número como precio chileno: 14990 -> $14.990
function formatoPrecio(valor) {
    return "$" + valor.toLocaleString("es-CL");
}

// ---------- Catálogo ----------

async function cargarCatalogo() {
    const grid = document.querySelector("#gridProductos");
    grid.innerHTML = '<div class="col-12"><div class="estado-catalogo">Cargando productos…</div></div>';

    try {
        productos = await obtenerProductos();
        mostrarFiltros();
        mostrarProductos();
        llenarSelector();
    } catch (error) {
        mostrarError(error.message);
    }
}

function mostrarError(mensaje) {
    const grid = document.querySelector("#gridProductos");
    grid.innerHTML = "";

    const caja = document.createElement("div");
    caja.className = "estado-catalogo error";

    const titulo = document.createElement("h3");
    titulo.textContent = "No pudimos cargar el catálogo";

    const texto = document.createElement("p");
    texto.textContent = mensaje;

    const boton = document.createElement("button");
    boton.className = "btn-fuego mt-2";
    boton.textContent = "Reintentar";
    boton.addEventListener("click", cargarCatalogo);

    caja.appendChild(titulo);
    caja.appendChild(texto);
    caja.appendChild(boton);

    const columna = document.createElement("div");
    columna.className = "col-12";
    columna.appendChild(caja);
    grid.appendChild(columna);
}

function mostrarFiltros() {
    const contenedor = document.querySelector("#filtros");
    contenedor.innerHTML = "";

    // Lista de líneas sin repetir, más la opción "Todos"
    const lineas = ["Todos"];
    productos.forEach((producto) => {
        if (!lineas.includes(producto.linea)) {
            lineas.push(producto.linea);
        }
    });

    lineas.forEach((linea) => {
        const boton = document.createElement("button");
        boton.type = "button";
        boton.className = "filtro";
        boton.textContent = linea;
        if (linea === filtroActual) {
            boton.classList.add("activo");
        }
        boton.addEventListener("click", () => {
            filtroActual = linea;
            mostrarFiltros();
            mostrarProductos();
        });
        contenedor.appendChild(boton);
    });
}

function mostrarProductos() {
    const grid = document.querySelector("#gridProductos");
    grid.innerHTML = "";

    let visibles = productos;
    if (filtroActual !== "Todos") {
        visibles = productos.filter((producto) => producto.linea === filtroActual);
    }

    if (visibles.length === 0) {
        grid.innerHTML = '<div class="col-12"><div class="estado-catalogo">No hay productos en esta línea.</div></div>';
        return;
    }

    visibles.forEach((producto) => {
        grid.appendChild(crearTarjeta(producto));
    });
}

function crearTarjeta(producto) {
    const columna = document.createElement("div");
    columna.className = "col-12 col-sm-6 col-lg-4 col-xl-3";

    const tarjeta = document.createElement("article");
    tarjeta.className = "tarjeta-producto";
    if (!producto.disponible) {
        tarjeta.classList.add("agotado");
    }

    // Cabecera de color con la línea y el código
    const cabecera = document.createElement("div");
    cabecera.className = "producto-cabecera";
    cabecera.setAttribute("data-linea", producto.linea);

    const chipLinea = document.createElement("span");
    chipLinea.className = "chip chip-linea";
    chipLinea.textContent = producto.linea;

    const codigo = document.createElement("span");
    codigo.className = "codigo";
    codigo.textContent = producto.id;

    cabecera.appendChild(chipLinea);
    cabecera.appendChild(codigo);

    // Cuerpo: estado de stock, nombre y descripción
    const cuerpo = document.createElement("div");
    cuerpo.className = "producto-cuerpo";

    const chipStock = document.createElement("span");
    chipStock.className = producto.disponible ? "chip chip-stock" : "chip chip-agotado";
    chipStock.textContent = producto.disponible ? "En stock" : "Sin stock";

    const nombre = document.createElement("h3");
    nombre.textContent = producto.nombre;

    const descripcion = document.createElement("p");
    descripcion.textContent = producto.descripcion;

    cuerpo.appendChild(chipStock);
    cuerpo.appendChild(nombre);
    cuerpo.appendChild(descripcion);

    // Pie: precio y botón
    const pie = document.createElement("div");
    pie.className = "producto-pie";

    const precio = document.createElement("div");
    precio.className = "precio";
    precio.textContent = formatoPrecio(producto.precio);

    const formato = document.createElement("small");
    formato.textContent = producto.formato;
    precio.appendChild(formato);

    const boton = document.createElement("button");
    boton.type = "button";
    boton.className = "btn-fuego";
    boton.textContent = producto.disponible ? "Agregar" : "Agotado";
    boton.disabled = !producto.disponible;
    boton.addEventListener("click", () => seleccionarProducto(producto.id));

    pie.appendChild(precio);
    pie.appendChild(boton);

    tarjeta.appendChild(cabecera);
    tarjeta.appendChild(cuerpo);
    tarjeta.appendChild(pie);
    columna.appendChild(tarjeta);
    return columna;
}

function llenarSelector() {
    const selector = document.querySelector("#cmbProducto");
    selector.innerHTML = '<option value="">Elige un corte o pack…</option>';

    productos.forEach((producto) => {
        const opcion = document.createElement("option");
        opcion.value = producto.id;
        opcion.textContent = producto.nombre + " (" + producto.formato + ") · " + formatoPrecio(producto.precio);
        opcion.disabled = !producto.disponible;
        selector.appendChild(opcion);
    });
}

// ---------- Selección de producto ----------

function buscarProducto(id) {
    return productos.find((producto) => producto.id === id);
}

function seleccionarProducto(id) {
    const producto = buscarProducto(id);
    if (!producto || !producto.disponible) {
        return;
    }
    const selector = document.querySelector("#cmbProducto");
    selector.value = id;
    selector.classList.remove("is-invalid");
    actualizarResumen();
    document.querySelector("#pedidos").scrollIntoView({ behavior: "smooth" });
}

function actualizarResumen() {
    const resumen = document.querySelector("#resumenProducto");
    const producto = buscarProducto(document.querySelector("#cmbProducto").value);

    if (!producto) {
        resumen.classList.add("d-none");
        return;
    }

    resumen.innerHTML = "";
    const nombre = document.createElement("span");
    nombre.textContent = producto.nombre + " · " + producto.formato;
    const precio = document.createElement("strong");
    precio.textContent = formatoPrecio(producto.precio);
    resumen.appendChild(nombre);
    resumen.appendChild(precio);
    resumen.classList.remove("d-none");
}

// ---------- Pedido ----------

// La fecha mínima de entrega es mañana
function configurarFecha() {
    const manana = new Date();
    manana.setDate(manana.getDate() + 1);
    document.querySelector("#txtFecha").min = manana.toISOString().split("T")[0];
}

// Marca el campo en rojo si no cumple la condición
function validarCampo(campo, esValido) {
    if (esValido) {
        campo.classList.remove("is-invalid");
    } else {
        campo.classList.add("is-invalid");
    }
    return esValido;
}

function validarFormulario() {
    const producto = document.querySelector("#cmbProducto");
    const nombre = document.querySelector("#txtNombre");
    const correo = document.querySelector("#txtCorreo");
    const direccion = document.querySelector("#txtDireccion");
    const fecha = document.querySelector("#txtFecha");
    const regexCorreo = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    const resultados = [
        validarCampo(producto, producto.value !== ""),
        validarCampo(nombre, nombre.value.trim().length >= 3),
        validarCampo(correo, regexCorreo.test(correo.value.trim())),
        validarCampo(direccion, direccion.value.trim().length >= 5),
        validarCampo(fecha, fecha.value !== "" && fecha.value >= fecha.min)
    ];

    return !resultados.includes(false);
}

async function enviarPedido(evento) {
    evento.preventDefault();

    if (!validarFormulario()) {
        document.querySelector(".is-invalid").scrollIntoView({ behavior: "smooth", block: "center" });
        return;
    }

    const boton = document.querySelector("#btnConfirmar");
    boton.disabled = true;
    boton.textContent = "Enviando pedido…";

    // Solo se envía el id del producto: el precio lo decide el servidor.
    const pedido = {
        productoId: document.querySelector("#cmbProducto").value,
        nombre: document.querySelector("#txtNombre").value.trim(),
        correo: document.querySelector("#txtCorreo").value.trim(),
        direccion: document.querySelector("#txtDireccion").value.trim(),
        fechaEntrega: document.querySelector("#txtFecha").value
    };

    try {
        const respuesta = await crearPedido(pedido);
        mostrarComprobante(respuesta);
        document.querySelector("#formularioPedido").reset();
        actualizarResumen();
    } catch (error) {
        mostrarFalloPedido(error.message);
    }

    boton.disabled = false;
    boton.textContent = "Confirmar pedido";
}

function mostrarComprobante(pedido) {
    const producto = buscarProducto(pedido.productoId);
    const panel = document.querySelector("#panelConfirmacion");
    panel.className = "comprobante";
    panel.innerHTML = "";

    const titulo = document.createElement("h3");
    titulo.textContent = "Pedido recibido";
    const aviso = document.createElement("p");
    aviso.className = "texto-suave mb-0";
    aviso.textContent = "Te enviamos el detalle y los datos de pago a tu correo.";

    const filas = [
        ["N° de pedido", pedido.id],
        ["Producto", producto.nombre + " (" + producto.formato + ")"],
        ["Total referencial", formatoPrecio(producto.precio)],
        ["Cliente", pedido.nombre],
        ["Correo", pedido.correo],
        ["Despacho", pedido.direccion],
        ["Entrega", pedido.fechaEntrega]
    ];

    const lista = document.createElement("dl");
    filas.forEach((fila) => {
        const dt = document.createElement("dt");
        dt.textContent = fila[0];
        const dd = document.createElement("dd");
        dd.textContent = fila[1];
        lista.appendChild(dt);
        lista.appendChild(dd);
    });

    panel.appendChild(titulo);
    panel.appendChild(aviso);
    panel.appendChild(lista);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function mostrarFalloPedido(mensaje) {
    const panel = document.querySelector("#panelConfirmacion");
    panel.className = "comprobante error";
    panel.innerHTML = "";

    const titulo = document.createElement("h3");
    titulo.textContent = "No pudimos registrar el pedido";
    const texto = document.createElement("p");
    texto.className = "texto-suave mb-0";
    texto.textContent = mensaje + " Tus datos siguen en el formulario, intenta de nuevo.";

    panel.appendChild(titulo);
    panel.appendChild(texto);
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---------- Eventos ----------

function registrarEventos() {
    document.querySelector("#formularioPedido").addEventListener("submit", enviarPedido);
    document.querySelector("#cmbProducto").addEventListener("change", actualizarResumen);

    // El botón del banner de promoción selecciona el pack familiar
    document.querySelector("#btnPromo").addEventListener("click", (evento) => {
        evento.preventDefault();
        seleccionarProducto("PACK-01");
    });

    // Al corregir un campo con error, el mensaje desaparece
    document.querySelectorAll("#formularioPedido .form-control, #formularioPedido .form-select").forEach((campo) => {
        campo.addEventListener("input", () => campo.classList.remove("is-invalid"));
    });
}

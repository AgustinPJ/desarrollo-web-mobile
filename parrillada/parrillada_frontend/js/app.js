/* =========================================================
   La Tienda del Fuego — lógica de la interfaz
   Catálogo generado con la API del DOM a partir del servicio
   (js/api.js), filtros por línea, selección de producto y
   envío del pedido con estados de carga, éxito y error.
   ========================================================= */

const estado = {
    productos: [],
    filtro: "Todos"
};

const formatoCLP = new Intl.NumberFormat("es-CL", { style: "currency", currency: "CLP", maximumFractionDigits: 0 });

const $ = (selector, raiz = document) => raiz.querySelector(selector);

/* Crea un elemento con clases, atributos y texto sin usar innerHTML,
   así ningún dato que venga del servicio se interpreta como HTML. */
function crear(etiqueta, { clase, texto, attrs } = {}, hijos = []) {
    const nodo = document.createElement(etiqueta);
    if (clase) nodo.className = clase;
    if (texto !== undefined) nodo.textContent = texto;
    if (attrs) Object.entries(attrs).forEach(([clave, valor]) => nodo.setAttribute(clave, valor));
    hijos.forEach((hijo) => nodo.append(hijo));
    return nodo;
}

document.addEventListener("DOMContentLoaded", () => {
    configurarFecha();
    registrarEventos();
    cargarCatalogo();
});

/* ---------- Catálogo ---------- */

async function cargarCatalogo() {
    mostrarCargando();
    try {
        estado.productos = await api.obtenerProductos();
        pintarFiltros();
        pintarProductos();
        poblarSelector();
    } catch (error) {
        mostrarError(error.message);
    }
}

function mostrarCargando() {
    const grid = $("#gridProductos");
    grid.replaceChildren();
    for (let i = 0; i < 4; i++) {
        grid.append(crear("div", { clase: "col-12 col-sm-6 col-lg-4 col-xl-3" }, [
            crear("div", { clase: "esqueleto", attrs: { "aria-hidden": "true" } })
        ]));
    }
    grid.setAttribute("aria-busy", "true");
}

function mostrarError(mensaje) {
    const grid = $("#gridProductos");
    const reintentar = crear("button", { clase: "btn-fuego mt-3", texto: "Reintentar", attrs: { type: "button" } });
    reintentar.addEventListener("click", cargarCatalogo);

    grid.replaceChildren(crear("div", { clase: "col-12" }, [
        crear("div", { clase: "estado-catalogo error", attrs: { role: "alert" } }, [
            crear("h3", { texto: "No pudimos cargar el catálogo" }),
            crear("p", { clase: "mb-0", texto: mensaje }),
            reintentar
        ])
    ]));
    grid.removeAttribute("aria-busy");
}

function pintarFiltros() {
    const lineas = ["Todos", ...new Set(estado.productos.map((p) => p.linea))];
    const contenedor = $("#filtros");
    contenedor.replaceChildren(...lineas.map((linea) => crear("button", {
        clase: `filtro${linea === estado.filtro ? " activo" : ""}`,
        texto: linea,
        attrs: { type: "button", "data-linea": linea, "aria-pressed": String(linea === estado.filtro) }
    })));
}

function pintarProductos() {
    const grid = $("#gridProductos");
    const visibles = estado.filtro === "Todos"
        ? estado.productos
        : estado.productos.filter((p) => p.linea === estado.filtro);

    grid.removeAttribute("aria-busy");

    if (visibles.length === 0) {
        grid.replaceChildren(crear("div", { clase: "col-12" }, [
            crear("div", { clase: "estado-catalogo" }, [
                crear("h3", { texto: "Sin productos en esta línea" }),
                crear("p", { clase: "mb-0", texto: "Prueba con otra categoría o vuelve pronto." })
            ])
        ]));
        return;
    }

    grid.replaceChildren(...visibles.map(crearTarjeta));
}

function crearTarjeta(producto) {
    const boton = crear("button", {
        clase: "btn-fuego",
        texto: producto.disponible ? "Agregar" : "Agotado",
        attrs: { type: "button", "data-producto": producto.id, "aria-label": `Pedir ${producto.nombre}` }
    });
    boton.disabled = !producto.disponible;

    const tarjeta = crear("article", { clase: `tarjeta-producto${producto.disponible ? "" : " agotado"}` }, [
        crear("div", { clase: "producto-cabecera", attrs: { "data-linea": producto.linea } }, [
            crear("span", { clase: "chip chip-linea", texto: producto.linea }),
            crear("span", { clase: "codigo", texto: producto.id, attrs: { "aria-hidden": "true" } })
        ]),
        crear("div", { clase: "producto-cuerpo" }, [
            crear("span", {
                clase: `chip ${producto.disponible ? "chip-stock" : "chip-agotado"} align-self-start`,
                texto: producto.disponible ? "En stock" : "Sin stock"
            }),
            crear("h3", { texto: producto.nombre }),
            crear("p", { texto: producto.descripcion })
        ]),
        crear("div", { clase: "producto-pie" }, [
            crear("div", { clase: "precio", texto: formatoCLP.format(producto.precio) }, [
                crear("small", { texto: producto.formato })
            ]),
            boton
        ])
    ]);

    return crear("div", { clase: "col-12 col-sm-6 col-lg-4 col-xl-3" }, [tarjeta]);
}

function poblarSelector() {
    const selector = $("#cmbProducto");
    const opciones = estado.productos.map((p) => {
        const opcion = crear("option", {
            texto: `${p.nombre} (${p.formato}) · ${formatoCLP.format(p.precio)}`,
            attrs: { value: p.id }
        });
        opcion.disabled = !p.disponible;
        return opcion;
    });
    selector.replaceChildren(selector.options[0], ...opciones);
}

/* ---------- Selección de producto ---------- */

function seleccionarProducto(id) {
    const producto = estado.productos.find((p) => p.id === id);
    if (!producto || !producto.disponible) return;

    const selector = $("#cmbProducto");
    selector.value = id;
    selector.classList.remove("is-invalid");
    actualizarResumen();
    $("#pedidos").scrollIntoView({ behavior: "smooth" });
}

function actualizarResumen() {
    const producto = estado.productos.find((p) => p.id === $("#cmbProducto").value);
    const resumen = $("#resumenProducto");

    if (!producto) {
        resumen.classList.add("d-none");
        return;
    }
    resumen.replaceChildren(
        crear("span", { texto: `${producto.nombre} · ${producto.formato}` }),
        crear("strong", { texto: formatoCLP.format(producto.precio) })
    );
    resumen.classList.remove("d-none");
}

/* ---------- Pedido ---------- */

function configurarFecha() {
    const manana = new Date();
    manana.setDate(manana.getDate() + 1);
    $("#txtFecha").min = manana.toISOString().split("T")[0];
}

const reglas = {
    cmbProducto: (v) => v !== "",
    txtNombre: (v) => v.trim().length >= 3,
    txtCorreo: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()),
    txtDireccion: (v) => v.trim().length >= 5,
    txtFecha: (v) => v !== "" && v >= $("#txtFecha").min
};

function validarCampo(campo) {
    const valido = reglas[campo.id](campo.value);
    campo.classList.toggle("is-invalid", !valido);
    return valido;
}

async function enviarPedido(evento) {
    evento.preventDefault();
    const campos = Object.keys(reglas).map((id) => document.getElementById(id));
    const validos = campos.map(validarCampo).every(Boolean);

    if (!validos) {
        const primero = campos.find((c) => c.classList.contains("is-invalid"));
        primero.focus({ preventScroll: true });
        primero.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
    }

    const boton = $("#btnConfirmar");
    boton.disabled = true;
    boton.textContent = "Enviando pedido…";

    // Solo se envía el id del producto: el precio lo decide el servidor, no el navegador.
    const pedido = {
        productoId: $("#cmbProducto").value,
        nombre: $("#txtNombre").value.trim(),
        correo: $("#txtCorreo").value.trim(),
        direccion: $("#txtDireccion").value.trim(),
        fechaEntrega: $("#txtFecha").value
    };

    try {
        const respuesta = await api.crearPedido(pedido);
        mostrarComprobante(respuesta);
        $("#formularioPedido").reset();
        actualizarResumen();
    } catch (error) {
        mostrarFalloPedido(error.message);
    } finally {
        boton.disabled = false;
        boton.textContent = "Confirmar pedido";
    }
}

function mostrarComprobante(pedido) {
    const producto = estado.productos.find((p) => p.id === pedido.productoId);
    const fecha = new Date(`${pedido.fechaEntrega}T12:00:00`).toLocaleDateString("es-CL", { weekday: "long", day: "numeric", month: "long" });

    const filas = [
        ["N° de pedido", pedido.id],
        ["Producto", producto ? `${producto.nombre} (${producto.formato})` : pedido.productoId],
        ["Total referencial", producto ? formatoCLP.format(producto.precio) : "Por confirmar"],
        ["Cliente", pedido.nombre],
        ["Correo", pedido.correo],
        ["Despacho", pedido.direccion],
        ["Entrega", fecha]
    ];

    const panel = $("#panelConfirmacion");
    panel.className = "comprobante";
    panel.replaceChildren(
        crear("h3", { texto: "Pedido recibido" }),
        crear("p", { clase: "texto-suave mb-0", texto: "Te enviamos el detalle y los datos de pago a tu correo." }),
        crear("dl", {}, filas.flatMap(([titulo, valor]) => [crear("dt", { texto: titulo }), crear("dd", { texto: valor })]))
    );
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function mostrarFalloPedido(mensaje) {
    const panel = $("#panelConfirmacion");
    panel.className = "comprobante";
    panel.style.borderColor = "rgba(245, 27, 25, 0.5)";
    panel.replaceChildren(
        crear("h3", { texto: "No pudimos registrar el pedido", attrs: { style: "color:#FF8A80" } }),
        crear("p", { clase: "texto-suave mb-0", texto: `${mensaje} Tus datos siguen en el formulario; intenta de nuevo.` })
    );
    panel.focus({ preventScroll: true });
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- Eventos ---------- */

function registrarEventos() {
    // Delegación: un solo listener atiende todos los botones "Agregar" y filtros generados.
    $("#gridProductos").addEventListener("click", (evento) => {
        const boton = evento.target.closest("[data-producto]");
        if (boton) seleccionarProducto(boton.dataset.producto);
    });

    $("#filtros").addEventListener("click", (evento) => {
        const boton = evento.target.closest("[data-linea]");
        if (!boton) return;
        estado.filtro = boton.dataset.linea;
        pintarFiltros();
        pintarProductos();
    });

    document.querySelectorAll(".banner-promo [data-producto]").forEach((enlace) => {
        enlace.addEventListener("click", (evento) => {
            evento.preventDefault();
            seleccionarProducto(enlace.dataset.producto);
        });
    });

    $("#cmbProducto").addEventListener("change", actualizarResumen);
    $("#formularioPedido").addEventListener("submit", enviarPedido);

    // Validación en vivo: el error desaparece apenas el campo queda correcto.
    Object.keys(reglas).forEach((id) => {
        document.getElementById(id).addEventListener("input", (evento) => {
            if (evento.target.classList.contains("is-invalid")) validarCampo(evento.target);
        });
    });

    // Cierra el menú móvil al elegir una sección.
    document.querySelectorAll("#menuPrincipal a").forEach((enlace) => {
        enlace.addEventListener("click", () => {
            const menu = bootstrap.Collapse.getInstance("#menuPrincipal");
            if (menu) menu.hide();
        });
    });
}

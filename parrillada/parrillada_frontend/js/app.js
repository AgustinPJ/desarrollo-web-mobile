//Catálogo unificado de productos 
const tiendaAPI = {
    "status": 200,
    "mensaje": "Productos disponibles obtenidos",
    "productos": [
        { "id": "PARR-01", "nombre": "Asado de Tira Angus (1kg)", "linea": "Parrilla Directa", "precio": 14990 },
        { "id": "PARR-02", "nombre": "Entraña Fina Seleccionada (1kg)", "linea": "Parrilla Directa", "precio": 17500 },
        { "id": "SMOK-01", "nombre": "Brisket Ahumado al Vacío (1.5kg)", "linea": "Smoked & Ready", "precio": 28500 },
        { "id": "SMOK-02", "nombre": "Costillar BBQ Maple Ahumado", "linea": "Smoked & Ready", "precio": 19990 },
        { "id": "PACK-01", "nombre": "Pack Familiar Parrillero (4 personas)", "linea": "Cajas Parrilleras", "precio": 34990 }
    ]
};

//Carga inicial del DOM
document.addEventListener("DOMContentLoaded", () => {
    inicializarTienda();
});

function inicializarTienda() {
    const tabla = document.getElementById("tablaProductos");
    const selectorFormulario = document.getElementById("cmbPack");

    tiendaAPI.productos.forEach((prod) => {
        // A. Poblamos la tabla de la tienda
        const fila = document.createElement("tr");
        fila.innerHTML = `
            <td class="ps-3 fw-bold text-secondary">${prod.id}</td>
            <td class="fw-bold" style="color: var(--color-botones);">${prod.nombre}</td>
            <td><span class="badge bg-secondary">${prod.linea}</span></td>
            <td>$${prod.precio.toLocaleString('es-CL')}</td>
            <td class="text-center"><span class="badge bg-success">En Stock</span></td>
            <td class="text-center">
                <button type="button" class="btn btn-sm btn-outline-warning" onclick="seleccionarParaComprar('${prod.id}');">
                    Pedir
                </button>
            </td>
        `;
        tabla.appendChild(fila);

        // Poblamos el selector del formulario
        const opcion = document.createElement("option");
        opcion.setAttribute("value", `${prod.nombre} ($${prod.precio.toLocaleString('es-CL')})`);
        opcion.innerText = `${prod.nombre} - $${prod.precio.toLocaleString('es-CL')}`;
        selectorFormulario.appendChild(opcion);
    });
}

//Función interactiva: al presionar "Pedir" en la tabla, salta al formulario y lo selecciona
function seleccionarParaComprar(idProducto) {
    const productoEncontrado = tiendaAPI.productos.find(p => p.id === idProducto);
    if (productoEncontrado) {
        const selectorFormulario = document.getElementById("cmbPack");
        selectorFormulario.value = `${productoEncontrado.nombre} ($${productoEncontrado.precio.toLocaleString('es-CL')})`;
        
        // Desplazamiento suave al formulario de compra
        document.getElementById("pedidos").scrollIntoView({ behavior: 'smooth' });
    }
}

// Validación y generación del comprobante
function validarYProcesarPedido() {
    const nombre = document.getElementById("txtNombre").value.trim();
    const correo = document.getElementById("txtCorreo").value.trim();
    const direccion = document.getElementById("txtDireccion").value.trim();
    const productoSeleccionado = document.getElementById("cmbPack").value;
    const fecha = document.getElementById("txtFecha").value;

    let esValido = true;

    // Validación Nombre
    if (nombre.length < 3) {
        document.getElementById("errorNombre").classList.remove("d-none");
        esValido = false;
    } else {
        document.getElementById("errorNombre").classList.add("d-none");
    }

    // Validación Correo
    const regexEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!regexEmail.test(correo)) {
        document.getElementById("errorCorreo").classList.remove("d-none");
        esValido = false;
    } else {
        document.getElementById("errorCorreo").classList.add("d-none");
    }

    // Validación Dirección
    if (direccion.length < 5) {
        document.getElementById("errorDireccion").classList.remove("d-none");
        esValido = false;
    } else {
        document.getElementById("errorDireccion").classList.add("d-none");
    }

    // Validación Producto
    if (productoSeleccionado === "") {
        document.getElementById("errorPack").classList.remove("d-none");
        esValido = false;
    } else {
        document.getElementById("errorPack").classList.add("d-none");
    }

    // Validación Fecha
    if (fecha === "") {
        document.getElementById("errorFecha").classList.remove("d-none");
        esValido = false;
    } else {
        document.getElementById("errorFecha").classList.add("d-none");
    }

    //  mostramos el comprobante
    if (esValido) {
        document.getElementById("detCliente").innerHTML = `<strong>Cliente:</strong> ${nombre}`;
        document.getElementById("detCorreo").innerHTML = `<strong>Correo:</strong> ${correo}`;
        document.getElementById("detDireccion").innerHTML = `<strong>Despacho en:</strong> ${direccion}`;
        document.getElementById("detProducto").innerHTML = `<strong>Producto Solicitado:</strong> ${productoSeleccionado}`;
        document.getElementById("detFecha").innerHTML = `<strong>Fecha de Entrega:</strong> ${fecha}`;

        const panel = document.getElementById("panelConfirmacion");
        panel.classList.remove("d-none");
        panel.scrollIntoView({ behavior: 'smooth' });

        document.getElementById("formularioPedido").reset();
    }
}
// Servicio simulado del catálogo y de los pedidos.
// En la Evaluación 2 se cambian estas URLs por las del API Gateway
// (por ejemplo http://localhost:8000/api/v1/products).
const URL_PRODUCTOS = "data/productos.json";

// Consulta: obtiene la lista de productos desde el servicio
async function obtenerProductos() {
    const respuesta = await fetch(URL_PRODUCTOS);
    if (!respuesta.ok) {
        throw new Error("El servicio respondió con error " + respuesta.status);
    }
    const datos = await respuesta.json();
    return datos.productos;
}

// Acción simulada: "envía" el pedido y devuelve un número de pedido.
// El navegador solo manda el id del producto; el precio lo calcula el servidor.
function crearPedido(pedido) {
    return new Promise((resolve) => {
        setTimeout(() => {
            const numero = "PED-" + Math.floor(Math.random() * 900000 + 100000);
            resolve({ id: numero, estado: "pendiente_pago", ...pedido });
        }, 900);
    });
}

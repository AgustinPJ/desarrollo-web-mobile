/* =========================================================
   Capa de acceso a servicios.
   Hoy lee un JSON local (servicio simulado). En la Eval 2 basta
   con cambiar API_BASE y las rutas para apuntar al API Gateway
   (por ejemplo GET /api/v1/products y POST /api/v1/orders);
   el resto de la app no cambia.
   ========================================================= */

const API_CONFIG = {
    modo: "simulado",               // "simulado" | "gateway"
    API_BASE: "",                   // ej: "http://localhost:8000/api/v1"
    timeoutMs: 8000
};

async function pedirJSON(url, opciones = {}) {
    const controlador = new AbortController();
    const temporizador = setTimeout(() => controlador.abort(), API_CONFIG.timeoutMs);

    try {
        const respuesta = await fetch(url, { ...opciones, signal: controlador.signal });
        if (!respuesta.ok) {
            throw new Error(`El servicio respondió ${respuesta.status}`);
        }
        return await respuesta.json();
    } catch (error) {
        if (error.name === "AbortError") {
            throw new Error("El servicio tardó demasiado en responder.");
        }
        if (location.protocol === "file:") {
            throw new Error("Abre el sitio desde un servidor (XAMPP: http://localhost/...) para que el navegador permita leer los datos.");
        }
        throw error;
    } finally {
        clearTimeout(temporizador);
    }
}

const api = {
    async obtenerProductos() {
        if (API_CONFIG.modo === "gateway") {
            return pedirJSON(`${API_CONFIG.API_BASE}/products`, { credentials: "include" });
        }
        const datos = await pedirJSON("data/productos.json");
        return datos.productos;
    },

    async crearPedido(pedido) {
        if (API_CONFIG.modo === "gateway") {
            return pedirJSON(`${API_CONFIG.API_BASE}/orders`, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(pedido)
            });
        }
        // Simulación: el servidor real calculará el total; aquí solo se imita su respuesta.
        await new Promise((resolver) => setTimeout(resolver, 900));
        return {
            id: `PED-${Date.now().toString().slice(-6)}`,
            estado: "pendiente_pago",
            ...pedido
        };
    }
};

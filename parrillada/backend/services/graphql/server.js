// GraphQL Gateway privado (puerto 4000, solo 127.0.0.1). Basado en el server.js de clases (Apollo + Express).
// NO lee ninguna base de datos: combina las APIs internas de orders, inventory y clients.
// Solo acepta llamadas del API Gateway (secreto de tramo) y usa la identidad que el gateway verificó.
const express = require('express');
const crypto = require('crypto');
const { ApolloServer, gql, ForbiddenError, ApolloError } = require('apollo-server-express');
const depthLimit = require('graphql-depth-limit');

const VAULT_ADDR = process.env.VAULT_ADDR || 'http://127.0.0.1:8200';
const VAULT_TOKEN = process.env.VAULT_TOKEN;
const URLS = {
    orders: process.env.ORDERS_URL || 'http://127.0.0.1:9002',
    inventory: process.env.INVENTORY_URL || 'http://127.0.0.1:9001',
    clients: process.env.CLIENTS_URL || 'http://127.0.0.1:9004'
};
// El esquema no tiene ciclos y su consulta más profunda (misPedidos.items.items.producto.nombre) llega a 4.
// El límite queda justo ahí: cualquier consulta más profunda se rechaza antes de ejecutar resolvers.
const PROFUNDIDAD_MAXIMA = 4;
const LIMITE_PAGINA = 20;
const TIMEOUT_MS = 5000;

let SECRETOS = {};

async function leerSecretosVault() {
    if (!VAULT_TOKEN) throw new Error('VAULT_TOKEN no está configurado');
    const respuesta = await fetch(`${VAULT_ADDR}/v1/secret/data/parrillada/graphql`, {
        headers: { 'X-Vault-Token': VAULT_TOKEN },
        signal: AbortSignal.timeout(TIMEOUT_MS)
    });
    if (!respuesta.ok) throw new Error('No fue posible leer los secretos desde Vault');
    const datos = await respuesta.json();
    return datos.data.data;
}

// Llamada a un servicio interno con el secreto del tramo graphql -> servicio.
async function llamar(servicio, ruta, contexto) {
    let respuesta;
    try {
        respuesta = await fetch(URLS[servicio] + ruta, {
            headers: {
                'X-Service-Name': 'graphql',
                'X-Service-Secret': SECRETOS[`salida_${servicio}`],
                'X-Correlation-Id': contexto.correlationId,
                'X-User-Id': contexto.userId,
                'X-User-Roles': contexto.roles.join(',')
            },
            signal: AbortSignal.timeout(TIMEOUT_MS)
        });
    } catch (e) {
        throw new ApolloError(`${servicio} no disponible`, 'SERVICIO_NO_DISPONIBLE');
    }
    if (respuesta.status === 404) return null;
    if (!respuesta.ok) throw new ApolloError(`Error consultando ${servicio}`, 'ERROR_INTERNO');
    return respuesta.json();
}

// Batching: se piden TODOS los productos de los pedidos en UNA sola llamada a inventory
// (en vez de una llamada por ítem, que sería el problema N+1). Se guardan en el contexto.
async function precargarProductos(ids, contexto) {
    const faltan = [...new Set(ids)].filter(id => !contexto.productos.has(id));
    if (faltan.length === 0) return;
    try {
        const lista = await llamar('inventory', `/productos?ids=${encodeURIComponent(faltan.join(','))}&limit=100`, contexto);
        for (const p of lista) contexto.productos.set(p.id, p);
        contexto.llamadasInventory += 1;
    } catch (e) {
        contexto.inventoryCaido = true; // los pedidos se devuelven igual, sin el detalle del producto
    }
}

function esOperador(contexto) {
    return contexto.roles.includes('operador');
}

const typeDefs = gql`
    type Producto {
        id: ID!
        nombre: String!
        linea: String!
        formato: String!
        descripcion: String!
        precio: Int!
        disponible: Boolean!
        "Solo visible para operador"
        stock: Int
    }
    type ItemPedido {
        productoId: String!
        nombre: String!
        cantidad: Int!
        precioUnitario: Int!
        subtotal: Int!
        "Datos actuales del catálogo (inventory). Null con error parcial si inventory no responde."
        producto: Producto
    }
    type Cliente {
        nombre: String!
    }
    type Pedido {
        id: ID!
        estado: String!
        total: Int!
        fechaEntrega: String!
        "Dato personal: solo el dueño del pedido o un operador"
        direccionEntrega: String
        creado: String!
        items: [ItemPedido!]!
        cliente: Cliente
    }
    type PaginaPedidos {
        items: [Pedido!]!
        total: Int!
        skip: Int!
        limit: Int!
    }
    type VentaDia {
        fecha: String!
        pedidos: Int!
        monto: Int!
    }
    type TopProducto {
        productoId: String!
        unidades: Int!
        monto: Int!
        producto: Producto
    }
    type Analitica {
        dias: Int!
        ventasPorDia: [VentaDia!]!
        topProductos: [TopProducto!]!
    }
    type Query {
        "Pedidos del usuario autenticado con el detalle de cada producto (orders + inventory)"
        misPedidos(skip: Int = 0, limit: Int = 10): PaginaPedidos!
        "Un pedido con productos (inventory) y nombre del cliente (clients)"
        resumenPedido(id: ID!): Pedido
        "Ventas por día y top de productos. Solo operador."
        analitica(dias: Int = 30): Analitica
    }
`;

function aPedido(p) {
    return {
        id: p.id,
        userId: p.user_id,
        estado: p.estado,
        total: p.total,
        fechaEntrega: p.fecha_entrega,
        direccionEntregaInterna: p.direccion_entrega,
        creado: p.creado,
        items: p.items.map(i => ({
            productoId: i.producto_id,
            nombre: i.nombre,
            cantidad: i.cantidad,
            precioUnitario: i.precio_unitario,
            subtotal: i.subtotal
        }))
    };
}

const resolvers = {
    Query: {
        async misPedidos(obj, { skip, limit }, contexto) {
            if (skip < 0 || limit < 1 || limit > LIMITE_PAGINA) {
                throw new ApolloError(`limit debe estar entre 1 y ${LIMITE_PAGINA}`, 'PARAMETRO_INVALIDO');
            }
            // Siempre los pedidos del propio usuario: el user_id viene del gateway, no del cliente.
            const pagina = await llamar('orders', `/orders?solo_propios=true&skip=${skip}&limit=${limit}`, contexto);
            const pedidos = pagina.items.map(aPedido);
            await precargarProductos(pedidos.flatMap(p => p.items.map(i => i.productoId)), contexto);
            return { items: pedidos, total: pagina.total, skip, limit };
        },
        async resumenPedido(obj, { id }, contexto) {
            const p = await llamar('orders', `/orders/${encodeURIComponent(id)}`, contexto);
            if (p === null) return null; // inexistente o ajeno: orders responde 404 igual
            const pedido = aPedido(p);
            await precargarProductos(pedido.items.map(i => i.productoId), contexto);
            return pedido;
        },
        async analitica(obj, { dias }, contexto) {
            if (!esOperador(contexto)) throw new ForbiddenError('Requiere rol operador');
            if (dias < 1 || dias > 365) throw new ApolloError('dias debe estar entre 1 y 365', 'PARAMETRO_INVALIDO');
            const datos = await llamar('orders', `/orders/analitica?dias=${dias}`, contexto);
            await precargarProductos(datos.top_productos.map(t => t.producto_id), contexto);
            return {
                dias: datos.dias,
                ventasPorDia: datos.ventas_por_dia,
                topProductos: datos.top_productos.map(t => ({ productoId: t.producto_id, unidades: t.unidades, monto: t.monto }))
            };
        }
    },
    Pedido: {
        direccionEntrega(pedido, args, contexto) {
            // Autorización por campo: dato personal solo para el dueño o el operador.
            if (pedido.userId === contexto.userId || esOperador(contexto)) return pedido.direccionEntregaInterna;
            throw new ForbiddenError('Campo restringido');
        },
        async cliente(pedido, args, contexto) {
            if (pedido.userId !== contexto.userId && !esOperador(contexto)) throw new ForbiddenError('Campo restringido');
            return llamar('clients', `/clientes/${encodeURIComponent(pedido.userId)}`, contexto);
        }
    },
    ItemPedido: {
        producto(item, args, contexto) {
            if (contexto.inventoryCaido) throw new ApolloError('inventory no disponible', 'SERVICIO_NO_DISPONIBLE');
            return contexto.productos.get(item.productoId) || null;
        }
    },
    TopProducto: {
        producto(top, args, contexto) {
            if (contexto.inventoryCaido) throw new ApolloError('inventory no disponible', 'SERVICIO_NO_DISPONIBLE');
            return contexto.productos.get(top.productoId) || null;
        }
    },
    Producto: {
        stock(producto, args, contexto) {
            if (!esOperador(contexto)) throw new ForbiddenError('Campo restringido');
            return producto.stock;
        }
    }
};

// Solo el API Gateway puede llamar a este servicio (mismo patrón verify_gateway de clases).
function verificarGateway(req, res, next) {
    const nombre = req.get('X-Service-Name') || '';
    const recibido = Buffer.from(req.get('X-Service-Secret') || '');
    const esperado = Buffer.from(SECRETOS[`entrada_${nombre}`] || '');
    const valido = nombre === 'gateway' && esperado.length > 0 && recibido.length === esperado.length
        && crypto.timingSafeEqual(recibido, esperado);
    if (!valido) return res.status(403).json({ detail: 'Solicitud no autorizada' });
    if (!req.get('X-User-Id')) return res.status(401).json({ detail: 'Sesión requerida' });
    next();
}

async function iniciar() {
    SECRETOS = await leerSecretosVault();
    const app = express();
    app.get('/health', (req, res) => res.json({ status: 'ok', service: 'graphql' }));
    app.use('/graphql', verificarGateway);

    const apolloServer = new ApolloServer({
        typeDefs,
        resolvers,
        validationRules: [depthLimit(PROFUNDIDAD_MAXIMA)], // consultas demasiado profundas se rechazan
        context: ({ req }) => ({
            userId: req.get('X-User-Id'),
            roles: (req.get('X-User-Roles') || '').split(',').filter(r => r),
            correlationId: req.get('X-Correlation-Id') || '',
            productos: new Map(),
            inventoryCaido: false,
            llamadasInventory: 0
        }),
        formatError: (err) => ({ message: err.message, path: err.path, extensions: { code: err.extensions && err.extensions.code } })
    });
    await apolloServer.start();
    apolloServer.applyMiddleware({ app, path: '/graphql', cors: false });

    app.listen(4000, '127.0.0.1', () => console.log('GraphQL Gateway privado en 127.0.0.1:4000/graphql'));
}

iniciar().catch(err => {
    console.error('No fue posible iniciar GraphQL:', err.message);
    process.exit(1);
});

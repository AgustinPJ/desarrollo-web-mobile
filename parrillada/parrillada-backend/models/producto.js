const mongoose = require('mongoose');

const productoSchema = new mongoose.Schema({
    nombre: String,
    estilo: String,       
    descripcion: String,
    precio: Number
});

module.exports = mongoose.model('Producto', productoSchema);
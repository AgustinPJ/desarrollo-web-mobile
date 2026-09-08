const express = require('express');
const mongoose = require('mongoose');
const cors = require('cors');
const { ApolloServer, gql } = require('apollo-server-express');

const Producto = require('./models/producto');


mongoose.connect('mongodb://localhost:27017/bd_parrilladas');
const typeDefs = gql`
    type Producto {
        id: ID!
        nombre: String!
        estilo: String!
        descripcion: String!
        precio: Number!
    }

    input ProductoInput {
        nombre: String
        estilo: String
        descripcion: String
        precio: Float
    }

    type Alert {
        message: String
    }

    type Query {
        getProductos: [Producto]
        getProductoById(id: ID!): Producto
    }

    type Mutation {
        addProducto(input: ProductoInput): Producto
        updateProducto(id: ID!, input: ProductoInput): Producto
        delProducto(id: ID!): Alert
    }
`;

const resolvers = {
    Query: {
        async getProductos(obj){
            const producto = await Producto.find();
            return producto
        },
        async getProductoById(obj,{id}){
            const productobus = await Producto.findById(id);
            if(productobus == null){
                return null;
            }
            else{
                return productobus;
            }
            
        }
    },
    Mutation:{
        async addProducto(obj,{input}){
            const producto = new Producto(input);
            await producto.save();
            return producto;
        },
        async updateProducto(obj,{id,input}){
            const Producto = await Producto.findByIdAndUpdate(id,input);
            return Producto;
        },
        async delProducto(obj,{id}){
            await Producto.deleteOne({_id: id});
            return "producto eliminado";
        }
    }
}


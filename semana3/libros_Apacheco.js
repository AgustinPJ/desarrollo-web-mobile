
const respuestaAPI = {
    "status": 200,
    "message": "Libros obtenidos correctamente",
    "data": [
        {
            "id": 101,
            "nombre": "Cien Años de Soledad",
            "autor": "Gabriel García Márquez"
        },
        {
            "id": 102,
            "nombre": "Don Quijote de la Mancha",
            "autor": "Miguel de Cervantes"
        }
    ]
};

respuestaAPI.data.forEach((libro) => {
    console.log(`${libro.nombre} - Autor: ${libro.autor}`);
});

let variable1 = null;
console.log(typeof(variable1));
variable1 = { "codigo": "LIB-99" };
console.log(typeof(variable1.codigo));

let variable2 = NaN;
console.log(typeof(variable2));
variable2 = 1 / 0;
console.log(typeof(variable2)); console.log(variable2);
variable2 = 1 / variable1;
console.log(typeof(variable2)); console.log(variable2);

let variable3;
console.log(typeof(variable3));
console.log(variable3 instanceof Object);
console.log(null instanceof Object);

try {
    variable2 = variable2 + y;
} catch (err) {
    console.log(`Error controlado: ${err}`);
}

function cargarLibros() {
    let cmb = document.getElementById("cmbLibro");
    respuestaAPI.data.forEach((libro) => {
        let opt = document.createElement("option");
        opt.setAttribute("value", libro.id);
        opt.innerText = `${libro.nombre} (${libro.autor})`;
        cmb.appendChild(opt);
    });
}


function agregarLibro() {
    let cmb = document.getElementById("cmbLibro");
    let id = document.getElementById("txtId").value;
    let nombre = document.getElementById("txtTitulo").value;

    if (id.trim() === "" || nombre.trim() === "") {
        alert("Por favor completa el código y el título del libro.");
        return;
    }

    let opt = document.createElement("option");
    opt.setAttribute("value", id);
    opt.innerText = `${nombre} (Código: ${id})`;
    cmb.appendChild(opt);

    document.getElementById("txtId").value = "";
    document.getElementById("txtTitulo").value = "";
}
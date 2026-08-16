<!DOCTYPE html>
<html lang="es">
    <head>
        <title>Pagina Principal</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/bootstrap.min.css" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/js/bootstrap.bundle.min.js"></script>
    </head>
    <body>
        <!-- navbar-->
        <nav class="navbar navbar-expand-sm bg-danger navbar-dark">
            <div class="container-fluid">
                <a class="navbar-brand" href="index.php"><img src="unab.png" alt="Avatar Logo" style="width:40px;" class="rounded-pill"></a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#collapsibleNavbar">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="collapsibleNavbar">
                    <ul class="navbar-nav">
                        <li class="nav-item dropdown">
                            <a class="nav-link dropdown-toggle" href="semana.php" role="button" data-bs-toggle="dropdown">semana</a>
                            <ul class="dropdown-menu">
                                <li><a class="dropdown-item" href="semana1.php">semana 1</a></li>
                                <li><a class="dropdown-item" href="semana2.php">semana 2</a></li>
                            </ul>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="curso.php">curso</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="alumnos.php">alumnos</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="profesor.php">profesor</a>
                        </li>
                    </ul>
                </div>
                <button type="button" class="btn btn-outline-light text-white" data-bs-toggle="modal" data-bs-target="#myModal">mi curso</button>
            </div>
        </nav>
        <!-- container -->
        <div class="container-fluid">
            <div class="card shadow-sm p-4 border-0">
                <h3 class="fw-bold text-primary mb-3">Semana 1: HTML, Bootstrap y Git</h3>
                <p class="lead text-secondary">
                    En la primera semana aprendimos a armar una página con HTML y a ordenar el contenido
                    usando las columnas de Bootstrap, para que se vea bien tanto en el celular como en el
                    computador. También empezamos a usar Git y GitHub para subir el avance del proyecto.
                </p>

                <h5 class="fw-bold text-dark mt-4">Lo que aprendí:</h5>
                <ul class="text-secondary">
                    <li>Etiquetas básicas de HTML: div, h3, p, ul, li, a.</li>
                    <li>Sistema de grilla de Bootstrap (row y col) para ordenar el contenido.</li>
                    <li>Comandos básicos de Git: git add, git commit y git push.</li>
                </ul>

                <div class="alert alert-info mt-3 mb-0">
                    <strong>Entregable:</strong> páginas con Bootstrap subidas a GitHub.
                </div>
            </div>
        </div>
        <!-- footer -->
        <div class="container-fluid bg-danger">
            <div class="row">
                <div class="col-12 d-flex justify-content-center" style="color:white">UNAB</div>
            </div>
        </div>
        <!-- modal -->
        <div class="modal fade" id="myModal">
            <div class="modal-dialog">
                <div class="modal-content">
                    <!-- Modal Header -->
                    <div class="modal-header">
                        <h4 class="modal-title">Modal Heading</h4>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <!-- Modal body -->
                    <div class="modal-body">
                        <form action="index.php">
                            <div class="mb-3 mt-3">
                                <label for="email" class="form-label">Email:</label>
                                <input type="email" class="form-control" id="email" placeholder="Enter email" name="email">
                            </div>
                            <div class="mb-3">
                                <label for="pwd" class="form-label">Password:</label>
                                <input type="password" class="form-control" id="pwd" placeholder="Enter password" name="pswd">
                            </div>
                            <div class="form-check mb-3">
                                <label class="form-check-label">
                                <input class="form-check-input" type="checkbox" name="remember"> Remember me
                                </label>
                            </div>
                            <button type="submit" class="btn btn-primary">Submit</button>
                        </form>
                    </div>
                    <!-- Modal footer -->
                    <div class="modal-footer">
                        <button type="button" class="btn btn-danger" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    </body>
</html>

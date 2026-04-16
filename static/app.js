const socket = io();
socket.on("actualizar",()=>cargar());

const ROL = "{{ user.get('rol','') }}";

if(ROL !== "admin"){
document.getElementById("btnUsers").style.display="none";
}

function req(url,data,msg){
fetch(url,{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify(data)
})
.then(r=>{
if(r.ok){
alert(msg);
cargar();
}else{
alert("Error");
}
});
}

function cargar(){

fetch("/datos").then(r=>r.json()).then(d=>{

listC.innerHTML = d.conductores.map(c=>
`<div>${c.nombre} - ${c.estado}</div>`
).join("");

listU.innerHTML = d.unidades.map(u=>
`<div>${u.placa} - ${u.estado}</div>`
).join("");

asigC.innerHTML = d.conductores.map(x=>`<option value="${x.id}">${x.nombre}</option>`).join("");
asigU.innerHTML = d.unidades.map(x=>`<option value="${x.id}">${x.placa}</option>`).join("");

finC.innerHTML = asigC.innerHTML;
finU.innerHTML = asigU.innerHTML;

inhUsel.innerHTML = asigU.innerHTML;
habUsel.innerHTML = asigU.innerHTML;

});
}

/* FLOTA */
function asignar(){
req("/asignar",{conductor_id:asigC.value,unidad_id:asigU.value},"OK");
}

function finalizar(){
req("/finalizar",{conductor_id:finC.value,unidad_id:finU.value},"OK");
}

function inhabilitar(){
req("/inhabilitar",{unidad_id:inhUsel.value,observacion:obs.value},"OK");
}

function habilitar(){
req("/habilitar",{unidad_id:habUsel.value},"OK");
}

/* USUARIOS */
function openUsers(){
modal.style.display="flex";
}

function closeUsers(){
modal.style.display="none";
}

function crearUsuario(){
req("/crear_usuario",{
username:u_user.value,
password:u_pass.value,
rol:u_rol.value
},"Usuario creado");
}

cargar();
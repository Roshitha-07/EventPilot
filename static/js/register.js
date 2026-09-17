const form = document.getElementById("registerForm");

form.addEventListener("submit", function(e){

    const password = document.getElementsByName("password")[0].value;
    const confirm = document.getElementsByName("confirm_password")[0].value;
    const phone = document.getElementsByName("phone")[0].value;

    if(password !== confirm){
        alert("Passwords do not match");
        e.preventDefault();
        return;
    }

    if(phone.length != 10){
        alert("Phone number must contain 10 digits");
        e.preventDefault();
        return;
    }

    if(isNaN(phone)){
        alert("Phone number should contain only digits");
        e.preventDefault();
        return;
    }

});
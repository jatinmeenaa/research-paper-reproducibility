document.addEventListener("DOMContentLoaded", function () {

    console.log("JavaScript is working!");

    const form = document.getElementById("searchForm");
    const input = document.getElementById("searchInput");
    const error = document.getElementById("searchError");

    if (!form || !input || !error) {
        console.error("HTML elements not found!");
        return;
    }

    form.addEventListener("submit", function (event) {

        // Stop page from reloading
        event.preventDefault();

        const query = input.value.trim();

        if (query === "") {
            error.style.color = "red";
            error.textContent = "Please enter a paper title!";
        } else {
            error.style.color = "green";
            error.textContent = "Searching for: " + query;
        }
    });
});
function toggleMpesaField() {
    const methodField = document.getElementById("id_payment_method");
    const mpesaField = document.getElementById("id_mpesa_amount_sent");
    if (!methodField || !mpesaField) return;

    const wrapper = mpesaField.closest("p") || mpesaField.parentElement;
    const isMpesa = methodField.value === "mpesa";
    wrapper.style.display = isMpesa ? "block" : "none";
    mpesaField.required = isMpesa;
}

document.addEventListener("DOMContentLoaded", () => {
    const methodField = document.getElementById("id_payment_method");
    if (methodField) {
        toggleMpesaField();
        methodField.addEventListener("change", toggleMpesaField);
    }

    document.querySelectorAll("[data-tabs]").forEach((tabsContainer) => {
        const buttons = tabsContainer.querySelectorAll(".tab-btn");
        buttons.forEach((button) => {
            button.addEventListener("click", () => {
                const targetId = button.getAttribute("data-tab-target");
                const targetPanel = document.getElementById(targetId);
                if (!targetPanel) return;

                buttons.forEach((btn) => btn.classList.remove("active"));
                document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));

                button.classList.add("active");
                targetPanel.classList.add("active");
            });
        });
    });
});

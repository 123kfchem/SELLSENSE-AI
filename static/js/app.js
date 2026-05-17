function toggleMpesaField() {
    const methodField = document.getElementById("id_payment_method");
    const mpesaField = document.getElementById("id_mpesa_amount_sent");
    if (!methodField || !mpesaField) return;

    const wrapper = mpesaField.closest("p") || mpesaField.parentElement;
    const isMpesa = methodField.value === "mpesa";
    wrapper.style.display = isMpesa ? "block" : "none";
    mpesaField.required = isMpesa;
}

const PASSWORD_EYE_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
const PASSWORD_EYE_OFF_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 0-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

function setPasswordToggleIcon(button, isVisible) {
    button.innerHTML = isVisible ? PASSWORD_EYE_OFF_ICON : PASSWORD_EYE_ICON;
}

function initPasswordToggles() {
    document.querySelectorAll('input[type="password"]').forEach((input) => {
        if (input.closest(".password-field")) return;

        const wrapper = document.createElement("div");
        wrapper.className = "password-field";
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const toggleBtn = document.createElement("button");
        toggleBtn.type = "button";
        toggleBtn.className = "password-toggle-btn";
        toggleBtn.setAttribute("aria-label", "Show password");
        toggleBtn.setAttribute("aria-pressed", "false");
        setPasswordToggleIcon(toggleBtn, false);

        toggleBtn.addEventListener("click", () => {
            const isHidden = input.type === "password";
            input.type = isHidden ? "text" : "password";
            toggleBtn.setAttribute("aria-label", isHidden ? "Hide password" : "Show password");
            toggleBtn.setAttribute("aria-pressed", isHidden ? "true" : "false");
            setPasswordToggleIcon(toggleBtn, isHidden);
        });

        wrapper.appendChild(toggleBtn);
    });
}

function toggleEmployerPasswordField() {
    const roleField = document.getElementById("id_role");
    const passwordWrapper = document.getElementById("employer-password-wrapper");
    const passwordInput = document.getElementById("id_employer_password");
    if (!roleField || !passwordWrapper || !passwordInput) return;
    const isEmployer = roleField.value === "employer";
    passwordWrapper.style.display = isEmployer ? "block" : "none";
    passwordInput.required = isEmployer;
    if (!isEmployer) {
        passwordInput.value = "";
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initPasswordToggles();

    const methodField = document.getElementById("id_payment_method");
    if (methodField) {
        toggleMpesaField();
        methodField.addEventListener("change", toggleMpesaField);
    }
    const roleField = document.getElementById("id_role");
    if (roleField) {
        toggleEmployerPasswordField();
        roleField.addEventListener("change", toggleEmployerPasswordField);
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

    const saleForm = document.getElementById("sale-form");
    const itemField = document.getElementById("id_item");
    const qtyField = document.getElementById("id_quantity");
    const totalPreview = document.getElementById("sale-total-preview");
    const itemPriceData = document.getElementById("item-price-data");
    if (saleForm && itemField && qtyField && totalPreview && itemPriceData) {
        let prices = {};
        try {
            prices = JSON.parse(itemPriceData.textContent || "{}");
        } catch (error) {
            prices = {};
        }

        const updateSalePreview = () => {
            const itemId = itemField.value;
            const qty = Number.parseFloat(qtyField.value || "0");
            const unitPrice = Number.parseFloat(prices[itemId] || "0");
            const total = unitPrice * (Number.isFinite(qty) ? qty : 0);
            totalPreview.textContent = Number.isFinite(total) ? total.toFixed(2) : "0.00";
        };

        updateSalePreview();
        itemField.addEventListener("change", updateSalePreview);
        qtyField.addEventListener("input", updateSalePreview);
    }

    const pieCanvas = document.getElementById("sales-pie-chart");
    const barCanvas = document.getElementById("sales-bar-chart");
    const stockInsightsTable = document.getElementById("stock-insights-table");
    if (pieCanvas && barCanvas && window.Chart) {
        let pieChart = null;
        let barChart = null;
        const renderCharts = (items) => {
            const labels = items.map((item) => item.name);
            const soldData = items.map((item) => Number.parseInt(item.total_sold || 0, 10));
            if (pieChart) {
                pieChart.destroy();
            }
            if (barChart) {
                barChart.destroy();
            }
            pieChart = new window.Chart(pieCanvas, {
                type: "pie",
                data: {
                    labels,
                    datasets: [{ data: soldData }],
                },
            });
            barChart = new window.Chart(barCanvas, {
                type: "bar",
                data: {
                    labels,
                    datasets: [{ label: "Items Sold", data: soldData, backgroundColor: "#4e73df" }],
                },
                options: {
                    scales: {
                        y: { beginAtZero: true },
                    },
                },
            });
        };
        const loadCharts = async () => {
            try {
                const [salesResponse, stockResponse] = await Promise.all([
                    fetch("/api/analytics/sales/"),
                    fetch("/api/analytics/stock/"),
                ]);
                if (!salesResponse.ok || !stockResponse.ok) return;
                const salesPayload = await salesResponse.json();
                const stockPayload = await stockResponse.json();
                renderCharts(salesPayload.items || []);
                if (stockInsightsTable) {
                    const tbody = stockInsightsTable.querySelector("tbody");
                    if (tbody) {
                        const rows = (stockPayload.items || [])
                            .map(
                                (item) =>
                                    `<tr><td>${item.name}</td><td>${item.total_sold}</td><td>${item.current_quantity}</td></tr>`
                            )
                            .join("");
                        tbody.innerHTML = rows || '<tr><td colspan="3">No stock insights available.</td></tr>';
                    }
                }
            } catch (error) {
                // Ignore silent refresh errors for dashboard charts.
            }
        };
        loadCharts();
        window.setInterval(loadCharts, 30000);
    }

    const superuserBusinessChartCanvas = document.getElementById("superuser-business-chart");
    const superuserStatusChartCanvas = document.getElementById("superuser-status-chart");
    if (superuserBusinessChartCanvas && superuserStatusChartCanvas && window.Chart) {
        let businessChart = null;
        let statusChart = null;
        const renderSuperuserCharts = (payload) => {
            const roleLabels = (payload.role_counts || []).map((row) => row.label);
            const roleTotals = (payload.role_counts || []).map((row) => row.total);
            const statusLabels = (payload.status_counts || []).map((row) => row.label);
            const statusTotals = (payload.status_counts || []).map((row) => row.total);
            if (businessChart) {
                businessChart.destroy();
            }
            if (statusChart) {
                statusChart.destroy();
            }
            businessChart = new window.Chart(superuserBusinessChartCanvas, {
                type: "bar",
                data: {
                    labels: roleLabels,
                    datasets: [{ label: "Registered Businesses", data: roleTotals, backgroundColor: "#36b9cc" }],
                },
                options: { scales: { y: { beginAtZero: true } } },
            });
            statusChart = new window.Chart(superuserStatusChartCanvas, {
                type: "pie",
                data: {
                    labels: statusLabels,
                    datasets: [{ data: statusTotals }],
                },
            });
        };

        const loadSuperuserStats = async () => {
            try {
                const response = await fetch("/api/superuser/business-stats/");
                if (!response.ok) return;
                const payload = await response.json();
                renderSuperuserCharts(payload);
            } catch (error) {
                // Keep page usable even if stats endpoint fails.
            }
        };

        loadSuperuserStats();
        window.setInterval(loadSuperuserStats, 30000);
    }
});

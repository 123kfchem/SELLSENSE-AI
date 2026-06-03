# SELLSENSE-AI

A professional multi-business sales management web application built with Django.

## Overview

SELLSENSE-AI is a secure Django-based business sales management system designed to support multiple businesses on one platform while keeping each business's data isolated and protected.

The system allows businesses to:

* manage sales
* track revenue
* monitor reports
* manage employees
* generate PDFs
* control inventory
* view analytics dashboards

The platform also includes an admin system for managing registered businesses and account access.

---

# Features

## Multi-Business Architecture

* Multiple businesses can use the same platform
* Each business sees only its own data
* Secure business-level data isolation
* Protected against cross-business access

## Authentication & Security

* Secure login system
* Business account activation/deactivation
* Password hashing using Django authentication
* Employer password management
* Admin password reset for businesses
* Protected routes using login authentication

## Sales Management

* Record daily sales
* Track total revenue
* Manage products and prices
* Update product prices anytime
* View sales history

## Employee Management

* Employer dashboard
* Employee account management
* Password reset functionality
* Role-based access

## Reports

### Weekly Reports

* Daily revenue totals
* Weekly revenue totals

### Monthly Reports

* Weekly revenue summaries
* Monthly total revenue

### Yearly Reports

* Monthly revenue summaries
* Yearly total revenue

## Dashboard Analytics

* Revenue charts
* Pie chart visualization
* Business statistics
* Sales summaries

## PDF Generation

* Generate PDF reports for daily sales
* Downloadable sales reports
* Revenue summaries included in PDFs

## Report Management

* Delete old reports after one year
* Secure report handling

---

# Technologies Used

* Python
* Django
* HTML5
* CSS3
* JavaScript
* Bootstrap
* Chart.js
* SQLite / PostgreSQL
* ReportLab / xhtml2pdf

---

# Installation Guide

## 1. Clone the Repository

```bash
git clone <your-repository-url>
cd SELLSENSE-AI
```

## 2. Create a Virtual Environment

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

---

# Install Dependencies

```bash
pip install -r requirements.txt
```

---

# Run Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

---

# Create Superuser

```bash
python manage.py createsuperuser
```

---

# Run Development Server

```bash
python manage.py runserver
```

Open your browser and visit:

```text
http://127.0.0.1:8000/
```

---

# Project Structure

```text
SELLSENSE-AI/
│
├── business/
├── sales/
├── reports/
├── templates/
├── static/
├── media/
├── manage.py
└── requirements.txt
```

---

# Security Features

* Business-level data filtering
* Protected views using @login_required
* Secure password hashing
* Prevention of unauthorized data access
* Business isolation architecture

---

# Example Business Filtering

```python
Sale.objects.filter(
    business=request.user.profile.business
)
```

---

# Admin Features

* Activate/deactivate businesses
* Reset business passwords
* Manage users
* Monitor platform activity

---

# Future Improvements

* Mobile app integration
* AI-powered analytics
* Email notifications
* Cloud deployment
* Advanced financial reporting
* Multi-language support

---

# Deployment

The project can be deployed using:

* PythonAnywhere
* Render
* Railway
* Heroku
* VPS hosting

---

# License

This project is licensed under the MIT License.

---

# Author

Developed by Erick Monyancha.

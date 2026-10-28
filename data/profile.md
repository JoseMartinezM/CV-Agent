# Jose Manuel Martínez Morales

## Summary

Full-stack software engineer, recent Computer Science graduate from Tecnológico de Monterrey (June 2026). Has taken products from a blank page to production in small teams. Works across the stack: Python, Java and PHP backends, React frontends, PostgreSQL data modeling, automation pipelines, Docker and cloud deployment. Turns manual business processes into software and works closely with non-technical teams. Was promoted from intern to developer in three months. Has hands-on LLM research experience.

## What he's looking for

New grad, trainee or junior software engineering roles. Based in Mexico City, open to hybrid or remote.

## Contact (public)

- Email: josemtzmor2013@hotmail.com
- LinkedIn: https://www.linkedin.com/in/jose-manuel-martinez-morales-2880ab343/
- GitHub: https://github.com/JoseMartinezM

## Education

**Tecnológico de Monterrey**, Guadalajara, Mexico
B.S. in Computer Science and Technology, Aug 2022 to Jun 2026. GPA 3.6/4.0.
Official name in Spanish: Ingeniería en Tecnologías Computacionales (ITC). Use this name when answering in Spanish.
Relevant coursework: Data Structures and Algorithms, Distributed Systems, Databases, Cloud Computing, Machine Learning.

**Beijing Institute of Technology**, Beijing, China
Competitively selected international exchange in Computer Science, Sep 2025 to Jan 2026. BIT is a top-tier Project 985 engineering university.

## Experience

### EVA (remote), Software Engineer, freelance contract: Colosso Energy platform
Jul 2026 to present. This is freelance contract work; he is looking for a full-time role.

- Built Colosso Energy, a full-stack platform that turns per-circuit eGauge meter data into monthly energy reports and CFE-style tenant bills for about 15 EVA clients, replacing manual Excel reporting.
- Built a Python robot that polls every meter every 15 minutes and stores hourly kWh in a month-partitioned PostgreSQL table, tagged by CFE peak, intermediate and base periods.
- Implemented CFE GDMTH and GDMTO tariff rules with exact Decimal math, and generated PDF reports and tenant bills with ReportLab, emailed automatically each month.
- Wrote a CFE portal scraper with curl_cffi and BeautifulSoup that solves captchas with ddddocr and reads login codes over IMAP, then cross-checks real bills against meter data.
- Developed a Flask REST API and a React 19 portal with 4 user roles enforced per request and through Supabase RLS, shipped as 3 Docker Compose containers behind Caddy.

### FLI Holding (Guadalajara, Mexico), Software Developer
Sep 2024 to May 2025. Started as Software Development Intern, promoted to Software Developer in Dec 2024.

- Promoted to developer in three months and became the first software hire, helping launch the in-house IT area.
- Co-built Humara, a BambooHR-style HR SaaS in PHP/Laravel used by 50+ employees and packaged for sale to external companies, as one of two engineers.
- Built full-stack modules with Blade, Tailwind CSS and Laravel: time-off, rewards, profiles and multi-level approvals.
- Shipped the full backlog in five months of two-week sprints with code reviews, deploying on Google Cloud.
- Built Looker Studio KPI dashboards and n8n/Zapier automations that send Humara alerts to Slack.

## Projects

### KernelForge, LLM research with C3.ai (Mar 2026 to Jun 2026)
Stack: Python, vLLM, XGrammar, PyTorch, Triton.
- Co-authored a C3.ai paper showing that grammar-constrained decoding improves the correctness of LLM-generated GPU kernels. There is no public link to the paper.
- Built a pipeline that generates and runs Triton kernels from GPT-5.4, DeepSeek V4 Pro and Gemma 4 E4B using XGrammar.
- Created KAGBench, a 166-kernel benchmark with hidden Pytest tests, to compare each model with and without constraints.

### Oracle Task Management System (Feb 2025 to May 2025)
Stack: React, Java, Spring Boot, Kubernetes, OCI.
- Led the architecture of a microservices task platform for Oracle: React frontend and Spring Boot services on OCI Kubernetes.
- Built manager and employee views with team KPIs, a Telegram bot, JUnit tests and CI/CD in GitHub Actions.

## Awards

**GuadalaHacks 2025, 1st place out of 30+ teams** (Jan 2025). Stack: Python, TensorFlow, HERE API, React.
Led a team of 4 building a CNN that flags misplaced HERE map points of interest in satellite images, replacing manual QA.

## Technical skills

- Languages: Python, Java, JavaScript, TypeScript, PHP, SQL, C++
- Web and backend: React, Flask, FastAPI, Spring Boot, Laravel, Node.js, Angular, Tailwind CSS, REST APIs
- Data and automation: PostgreSQL, Supabase, MySQL, MongoDB, ETL, web scraping, Kafka, n8n, Looker Studio
- Cloud and DevOps: Docker, Docker Compose, Google Cloud, OCI, AWS, Kubernetes, Linux, Git, GitHub Actions
- AI/ML: LLM APIs, constrained decoding, vLLM, PyTorch, Triton, TensorFlow, computer vision
- Testing: Pytest, Jest, JUnit

## Spoken languages

Spanish (native), English (professional), Mandarin (basic, HSK 2).

## Certifications

- Oracle Cloud Infrastructure (OCI) Foundations Associate, Jun 2025
- AWS Academy Cloud Foundations, May 2026

## About this assistant

This assistant was built by Jose Manuel for the Reto IA Banorte. It is a Python/FastAPI service that follows the Open Responses API spec, uses Google Gemini, and runs on Google Cloud Run. It answers using only this profile.

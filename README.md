# EventPilot - Event Management System

## Milestone 2: Venue & Speaker Operations

### New user experience
The first page now contains exactly two main portals:

1. **Event Organizer** - opens the organizer login and then the Organizer Command Center.
2. **Participant** - opens the participant login and then the Participant Dashboard.

### Organizer Command Center
The organizer can access:
- Add Venue
- Venue Agent
- Venue Scheduling
- Add Speaker
- Speaker Agent
- Speaker Scheduling
- Smart Session Scheduling
- Session Analytics
- Participant Management
- Participant Check-In
- AI Insights

### Venue Agent criteria
Venues can be selected/ranked using:
- Budget
- Expected attendee capacity
- Area/location
- Rating
- Cleanliness
- Projector
- Sound system
- Seating arrangement
- Feedback and other requirements

### Speaker Agent criteria
Speakers can be selected/ranked using:
- Budget
- Expertise
- Required date
- Required time
- Speaker availability
- Speaker requirements
- Rating and feedback

### Participant portal
Participants can:
- Create an account
- Login
- Register for the event
- Receive a registration token and QR code
- View registration status
- View scheduled sessions
- View check-in status

### Smart scheduling
The scheduler prevents overlapping bookings for the same venue or speaker.

### Setup
1. Install MySQL and run `database/schema.sql`.
2. Update `config.py` with MySQL and mail credentials.
3. From the folder containing `requirements.txt`, run:
   `pip install -r requirements.txt`
4. Run:
   `python app.py`

### Demo organizer
Email: `organizer@event.com`
Password: `organizer123`


## Participant Portal Flow

Home -> Participant -> Participant Login -> Participant Portal.

The Participant Portal contains the same five core options from the original Event Management System:
1. Register
2. Dashboard
3. Check-In
4. Attendees
5. AI Insights

Organizer functionality from Milestone 2 is unchanged. Organizer-only routes remain protected by the organizer role.

Participant-specific pages were added so attendees do not receive access to organizer-only operations or private attendee contact information.


## Participant Login

Click **Participant** on the home page, then use:

- Email: `participant@event.com`
- Password: `participant123`

This demo participant is inserted by `database/schema.sql`.

If you already created the database from an older ZIP, run the following once in MySQL:

```sql
USE event_management;
INSERT INTO users(name,email,password,role)
SELECT 'Demo Participant','participant@event.com','participant123','attendee'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email='participant@event.com');
```

You can also create your own participant account from **Create an account** on the Participant Login page.

## Milestone 3 — Sponsorship & Operations Intelligence

The organizer portal now includes a **Sponsors & Operations** card. Opening it provides a single Milestone 3 command centre with:

1. AI-powered Sponsorship Agent
2. AI-powered Incident Agent
3. Sponsor performance analytics
4. Incident management workflows
5. Intelligent operational alerts
6. AI-based recommendations
7. Event operational efficiency actions
8. Real-time monitoring dashboard with automatic refresh
9. Incident prioritization and escalation
10. Analytical sponsor report export (CSV)

### New route
- `/sponsors` — complete Milestone 3 dashboard
- `/sponsors/incident` — incident intake
- `/sponsors/incident/<id>/update` — incident workflow updates
- `/sponsors/alert/<id>/read` — dismiss an operational alert
- `/sponsors/report.csv` — sponsor performance report

### Database
The application automatically creates the `sponsors`, `incidents`, and `operational_alerts` tables on the first request. The same SQL definitions are also included at the bottom of `database/schema.sql`.

### Demo sponsor data
If the `sponsors` table is empty, four sample sponsors are inserted automatically so the Milestone 3 screens have meaningful data for presentation/testing.


## Milestone 4 – Event Intelligence Control Center

The Organizer portal now includes five clickable milestone cards:

1. **Build Event Intelligence Engine** – event data, participants, sponsors, incidents, AI agents, agent communication, alerts, database and APIs.
2. **Develop Executive Dashboards** – event KPIs, attendance, sponsor performance, incident status, live alerts, charts/analytics and overall performance.
3. **Implement Agent Orchestration** – central orchestrator, specialist agents, task routing, workflows and response handling.
4. **Perform End-to-End Testing** – registration/login, participant, sponsor, incident-alert, agent, dashboard, API/database, error and performance checks.
5. **Deploy Production-Ready Platform** – frontend/backend, production database, environment variables, authentication/security, API configuration, error handling, monitoring/logging and documentation.

Each card navigates to its dedicated operational page.


## Milestone Control Center — Completed

The Organizer Command Center now provides five fully clickable milestone cards:

1. **Build Event Intelligence Engine** (`/intelligence`) — live data counts, connected data sources, AI-agent layer and direct links to operational modules.
2. **Develop Executive Dashboards** (`/executive-dashboard`) — live event-health score, attendance/sponsorship/operations indicators, KPI cards, incident health and quick actions.
3. **Implement Agent Orchestration** (`/agent-orchestration`) — six active specialist agents, task examples, deterministic routing, workflow steps and a visible routing trail.
4. **Perform End-to-End Testing** (`/end-to-end-testing`) — runs real application/database/routing checks and reports Passed/Failed results instead of displaying a fake completed state.
5. **Deploy Production-Ready Platform** (`/deployment`) — interactive readiness scan for frontend, backend, database, environment variables, security, APIs, monitoring and documentation.

### Important
- The deployment page is a readiness/configuration checker; it does not pretend to deploy to an external cloud account automatically.
- Production secrets should be supplied through environment variables rather than committed to source control.
- The new pages use the existing MySQL-backed application data and remain protected by the organizer login.

## Latest UI updates

- Executive Dashboard now has simple charts for attendance, incident status, sponsor value, sponsor package mix and 7-day registrations.
- Deployment page now has a small Project Guide PDF download.
- The PDF covers setup, modules, data, agents, testing, release checks and common errors.
- Content is kept short so the pages are easy to read during a demo.

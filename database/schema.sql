CREATE DATABASE IF NOT EXISTS event_management;
USE event_management;

CREATE TABLE IF NOT EXISTS users (
 id INT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(100) NOT NULL,
 email VARCHAR(150) UNIQUE NOT NULL,
 password VARCHAR(255) NOT NULL,
 role ENUM('organizer','attendee') NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendees (
 id INT AUTO_INCREMENT PRIMARY KEY,
 registration_token VARCHAR(30) UNIQUE NOT NULL,
 user_id INT,
 name VARCHAR(100) NOT NULL,
 email VARCHAR(150) NOT NULL,
 phone VARCHAR(30) NOT NULL,
 password VARCHAR(255),
 gender VARCHAR(20),
 location VARCHAR(100),
 category VARCHAR(30),
 vip VARCHAR(10) DEFAULT 'No',
 attendance VARCHAR(20) DEFAULT 'Absent',
 status VARCHAR(30) DEFAULT 'Registered',
 qr_path VARCHAR(255),
 checkin_time DATETIME NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS venues (
 id INT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(150) NOT NULL,
 area VARCHAR(100) NOT NULL,
 budget DECIMAL(12,2) NOT NULL,
 capacity INT NOT NULL,
 rating DECIMAL(3,2) DEFAULT 0,
 cleanliness DECIMAL(3,2) DEFAULT 0,
 projector VARCHAR(20) DEFAULT 'No',
 sound_system VARCHAR(20) DEFAULT 'No',
 seating_arrangement VARCHAR(100),
 feedback TEXT,
 other_requirements TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS speakers (
 id INT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(150) NOT NULL,
 expertise VARCHAR(200),
 budget DECIMAL(12,2) NOT NULL,
 available_date DATE NOT NULL,
 start_time TIME NOT NULL,
 end_time TIME NOT NULL,
 requirements TEXT,
 rating DECIMAL(3,2) DEFAULT 0,
 feedback TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
 id INT AUTO_INCREMENT PRIMARY KEY,
 title VARCHAR(200) NOT NULL,
 session_date DATE NOT NULL,
 start_time TIME NOT NULL,
 end_time TIME NOT NULL,
 venue_id INT NOT NULL,
 speaker_id INT NOT NULL,
 expected_attendees INT DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (venue_id) REFERENCES venues(id) ON DELETE CASCADE,
 FOREIGN KEY (speaker_id) REFERENCES speakers(id) ON DELETE CASCADE
);

INSERT INTO users(name,email,password,role)
SELECT 'Event Organizer','organizer@event.com','organizer123','organizer'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email='organizer@event.com');


-- Demo participant account for testing the Participant portal
INSERT INTO users(name,email,password,role)
SELECT 'Demo Participant','participant@event.com','participant123','attendee'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE email='participant@event.com');

-- ============================================================================
-- MILESTONE 3: Sponsorship + Incident Intelligence
-- ============================================================================
CREATE TABLE IF NOT EXISTS sponsors (
 id INT AUTO_INCREMENT PRIMARY KEY,
 name VARCHAR(150) NOT NULL,
 company VARCHAR(180) NOT NULL,
 contact_email VARCHAR(180),
 phone VARCHAR(30),
 package VARCHAR(30) DEFAULT 'Silver',
 budget DECIMAL(12,2) DEFAULT 0,
 committed_amount DECIMAL(12,2) DEFAULT 0,
 delivered_value DECIMAL(12,2) DEFAULT 0,
 leads INT DEFAULT 0,
 impressions INT DEFAULT 0,
 engagements INT DEFAULT 0,
 status VARCHAR(30) DEFAULT 'Active',
 rating DECIMAL(4,2) DEFAULT 0,
 contract_start DATE NULL,
 contract_end DATE NULL,
 contract_value DECIMAL(12,2) DEFAULT 0,
 deliverables TEXT,
 payment_status VARCHAR(30) DEFAULT 'Pending',
 amount_paid DECIMAL(12,2) DEFAULT 0,
 branding_requirements TEXT,
 notes TEXT,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS incidents (
 id INT AUTO_INCREMENT PRIMARY KEY,
 title VARCHAR(180) NOT NULL,
 category VARCHAR(80) NOT NULL,
 description TEXT,
 severity VARCHAR(20) DEFAULT 'Medium',
 status VARCHAR(30) DEFAULT 'Open',
 assigned_to VARCHAR(120),
 escalation_level INT DEFAULT 0,
 reported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
 due_at DATETIME NULL,
 resolution TEXT,
 updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS incident_logs (
 id INT AUTO_INCREMENT PRIMARY KEY,
 incident_id INT NOT NULL,
 action VARCHAR(150) NOT NULL,
 note TEXT,
 actor VARCHAR(120),
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (incident_id) REFERENCES incidents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS operational_alerts (
 id INT AUTO_INCREMENT PRIMARY KEY,
 title VARCHAR(180) NOT NULL,
 message TEXT NOT NULL,
 priority VARCHAR(20) DEFAULT 'Medium',
 source VARCHAR(80) DEFAULT 'System',
 is_read TINYINT(1) DEFAULT 0,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

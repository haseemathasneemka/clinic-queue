CREATE TABLE IF NOT EXISTS doctors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    specialization VARCHAR(100) NOT NULL,
    room VARCHAR(20) NOT NULL,
    is_available TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'receptionist', 'doctor') NOT NULL,
    doctor_id INT NULL,
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
);

-- One row per doctor per day, locked with SELECT ... FOR UPDATE
-- so two receptionists can never issue the same token number.
CREATE TABLE IF NOT EXISTS daily_counters (
    doctor_id INT NOT NULL,
    counter_date DATE NOT NULL,
    last_no INT NOT NULL DEFAULT 0,
    PRIMARY KEY (doctor_id, counter_date),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,
    public_code VARCHAR(12) NOT NULL UNIQUE,
    doctor_id INT NOT NULL,
    token_date DATE NOT NULL,
    token_no INT NOT NULL,
    patient_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    source ENUM('online', 'walkin') NOT NULL,
    status ENUM('waiting', 'serving', 'done', 'absent') NOT NULL DEFAULT 'waiting',
    created_at DATETIME NOT NULL,
    called_at DATETIME NULL,
    completed_at DATETIME NULL,
    UNIQUE KEY uq_token (doctor_id, token_date, token_no),
    INDEX idx_queue (doctor_id, token_date, status),
    FOREIGN KEY (doctor_id) REFERENCES doctors(id) ON DELETE CASCADE
);

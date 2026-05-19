-- University dataset matching the Ontop VKG tutorial schema
-- academic.position codes: 1=Full Professor, 2=Associate Professor, 3=Assistant Professor, 9=PostDoc

CREATE TABLE student (
    s_id   INTEGER PRIMARY KEY,
    fname  VARCHAR(50) NOT NULL,
    lname  VARCHAR(50) NOT NULL
);

CREATE TABLE academic (
    a_id     INTEGER PRIMARY KEY,
    fname    VARCHAR(50) NOT NULL,
    lname    VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL
);

CREATE TABLE course (
    c_id  INTEGER PRIMARY KEY,
    title VARCHAR(100) NOT NULL
);

CREATE TABLE teaching (
    a_id INTEGER NOT NULL REFERENCES academic(a_id),
    c_id INTEGER NOT NULL REFERENCES course(c_id),
    PRIMARY KEY (a_id, c_id)
);

CREATE TABLE course_registration (
    s_id INTEGER NOT NULL REFERENCES student(s_id),
    c_id INTEGER NOT NULL REFERENCES course(c_id),
    PRIMARY KEY (s_id, c_id)
);

-- Students
INSERT INTO student VALUES (1,  'Mary',    'Smith');
INSERT INTO student VALUES (2,  'John',    'Doe');
INSERT INTO student VALUES (3,  'Alice',   'Brown');
INSERT INTO student VALUES (4,  'Bob',     'Jones');
INSERT INTO student VALUES (5,  'Carol',   'White');
INSERT INTO student VALUES (6,  'David',   'Green');
INSERT INTO student VALUES (7,  'Eve',     'Black');
INSERT INTO student VALUES (8,  'Frank',   'Taylor');
INSERT INTO student VALUES (9,  'Grace',   'Wilson');
INSERT INTO student VALUES (10, 'Henry',   'Moore');

-- Academics (positions: 1=FullProf, 2=AssocProf, 3=AsstProf, 9=PostDoc)
INSERT INTO academic VALUES (1, 'Roger',   'Smith',   1);  -- Full Professor
INSERT INTO academic VALUES (2, 'Sarah',   'Jones',   1);  -- Full Professor
INSERT INTO academic VALUES (3, 'Michael', 'Brown',   2);  -- Associate Professor
INSERT INTO academic VALUES (4, 'Laura',   'Davis',   3);  -- Assistant Professor
INSERT INTO academic VALUES (5, 'James',   'Wilson',  9);  -- PostDoc
INSERT INTO academic VALUES (6, 'Anna',    'Taylor',  9);  -- PostDoc

-- Courses
INSERT INTO course VALUES (1, 'Information Systems');
INSERT INTO course VALUES (2, 'Software Engineering');
INSERT INTO course VALUES (3, 'Database Systems');
INSERT INTO course VALUES (4, 'Artificial Intelligence');
INSERT INTO course VALUES (5, 'Computer Networks');

-- Teaching assignments
INSERT INTO teaching VALUES (1, 1);  -- Roger Smith teaches Information Systems
INSERT INTO teaching VALUES (1, 3);  -- Roger Smith teaches Database Systems
INSERT INTO teaching VALUES (2, 2);  -- Sarah Jones teaches Software Engineering
INSERT INTO teaching VALUES (2, 4);  -- Sarah Jones teaches Artificial Intelligence
INSERT INTO teaching VALUES (3, 5);  -- Michael Brown teaches Computer Networks
INSERT INTO teaching VALUES (4, 1);  -- Laura Davis teaches Information Systems
INSERT INTO teaching VALUES (5, 2);  -- James Wilson teaches Software Engineering

-- Course registrations
INSERT INTO course_registration VALUES (1, 1);
INSERT INTO course_registration VALUES (1, 3);
INSERT INTO course_registration VALUES (2, 1);
INSERT INTO course_registration VALUES (2, 2);
INSERT INTO course_registration VALUES (3, 3);
INSERT INTO course_registration VALUES (3, 4);
INSERT INTO course_registration VALUES (4, 2);
INSERT INTO course_registration VALUES (4, 5);
INSERT INTO course_registration VALUES (5, 1);
INSERT INTO course_registration VALUES (5, 4);
INSERT INTO course_registration VALUES (6, 3);
INSERT INTO course_registration VALUES (6, 5);
INSERT INTO course_registration VALUES (7, 2);
INSERT INTO course_registration VALUES (7, 4);
INSERT INTO course_registration VALUES (8, 1);
INSERT INTO course_registration VALUES (8, 3);
INSERT INTO course_registration VALUES (9, 4);
INSERT INTO course_registration VALUES (9, 5);
INSERT INTO course_registration VALUES (10, 2);
INSERT INTO course_registration VALUES (10, 3);

-- Researcher-only known-correct control. Never uploaded to a model agent.
BEGIN;
CREATE TABLE employees.gender_statistics AS
WITH active AS (SELECT DISTINCT employee_id FROM employees.salary WHERE to_date=DATE '9999-01-01')
SELECT e.gender::varchar AS gender, count(*)::integer AS total_employees,
       count(a.employee_id)::integer AS current_employees,
       count(a.employee_id)::numeric / NULLIF((SELECT count(*) FROM active),0) * 100 AS percentage_of_workforce
FROM employees.employee e LEFT JOIN active a ON a.employee_id=e.id
WHERE e.gender IN ('M','F') GROUP BY e.gender;
CREATE TABLE employees.age_group_analysis AS
WITH active AS (
 SELECT DISTINCT ON (employee_id) employee_id,amount FROM employees.salary
 WHERE to_date=DATE '9999-01-01' ORDER BY employee_id,from_date DESC,amount DESC
), ages AS (
 SELECT e.*,extract(year FROM age(DATE '2002-08-01',birth_date))::integer AS years
 FROM employees.employee e WHERE birth_date IS NOT NULL
)
SELECT (CASE WHEN years BETWEEN 20 AND 29 THEN '20-29' WHEN years BETWEEN 30 AND 39 THEN '30-39'
 WHEN years BETWEEN 40 AND 49 THEN '40-49' WHEN years BETWEEN 50 AND 59 THEN '50-59' ELSE '60+' END)::varchar AS age_group,
 count(*)::integer AS employee_count,avg(amount) AS avg_salary,
 avg(DATE '2002-08-01'-hire_date) AS avg_tenure_days
FROM ages JOIN active ON employee_id=id WHERE years>=20 GROUP BY 1;
CREATE TABLE employees.birth_month_distribution AS
WITH active AS (SELECT DISTINCT employee_id FROM employees.salary WHERE to_date=DATE '9999-01-01')
SELECT m::integer AS birth_month,
 to_char(DATE '2000-01-01'+(m-1)*interval '1 month','FMMonth')::varchar AS month_name,
 count(e.id)::integer AS employee_count,count(a.employee_id)::integer AS current_employee_count
FROM generate_series(1,12) m LEFT JOIN employees.employee e ON extract(month FROM e.birth_date)=m
LEFT JOIN active a ON a.employee_id=e.id GROUP BY m;
CREATE TABLE employees.hiring_year_summary AS
WITH active AS (SELECT DISTINCT employee_id FROM employees.salary WHERE to_date=DATE '9999-01-01')
SELECT extract(year FROM e.hire_date)::integer AS hire_year,count(*)::integer AS employees_hired,
 count(a.employee_id)::integer AS still_employed,count(a.employee_id)::numeric/NULLIF(count(*),0)*100 AS retention_rate
FROM employees.employee e LEFT JOIN active a ON a.employee_id=e.id WHERE e.hire_date IS NOT NULL GROUP BY 1;
COMMIT;

-- Researcher-only known-correct control, following the original eight steps.
BEGIN;
INSERT INTO "Employee" ("EmployeeId","FirstName","LastName","Title","ReportsTo","BirthDate","HireDate","Address","City","State","Country","PostalCode","Phone","Fax","Email") VALUES
(9,'Sarah','Johnson','Sales Support Agent',2,'1985-03-15','2009-01-10','123 Oak Street','Calgary','AB','Canada','T2P 5G3','+1 (403) 555-0123','+1 (403) 555-0124','sarah.johnson@chinookcorp.com'),
(10,'Mike','Chen','Sales Support Agent',2,'1982-08-22','2009-01-10','456 Pine Ave','Calgary','AB','Canada','T2P 5G4','+1 (403) 555-0125','+1 (403) 555-0126','mike.chen@chinookcorp.com');
UPDATE "Employee" SET "Title"='CEO' WHERE "EmployeeId"=1;
UPDATE "Employee" SET "Phone"='+1 (403) 555-9999' WHERE "EmployeeId"=2;
UPDATE "Employee" SET "Title"='IT Specialist' WHERE "Title"='IT Staff';
UPDATE "Customer" SET "SupportRepId"=9 WHERE "CustomerId" IN (1,2,3);
UPDATE "Customer" SET "SupportRepId"=10 WHERE "CustomerId" IN (4,5,6);
UPDATE "Employee" SET "ReportsTo"=1 WHERE "EmployeeId" IN (9,10);
CREATE TABLE employee_performance (employee_id integer REFERENCES "Employee"("EmployeeId"),customers_assigned integer,performance_score decimal);
INSERT INTO employee_performance SELECT "EmployeeId",(SELECT count(*) FROM "Customer" WHERE "SupportRepId"="EmployeeId"),
 CASE "EmployeeId" WHEN 9 THEN 4.5 ELSE 4.2 END FROM "Employee" WHERE "EmployeeId" IN (9,10);
UPDATE "Employee" SET "ReportsTo"=(SELECT "ReportsTo" FROM "Employee" WHERE "EmployeeId"=7) WHERE "ReportsTo"=7;
UPDATE "Customer" SET "SupportRepId"=(SELECT "ReportsTo" FROM "Employee" WHERE "EmployeeId"=7) WHERE "SupportRepId"=7;
DELETE FROM "Employee" WHERE "EmployeeId"=7;
UPDATE "Employee" SET "Title"='Senior IT Specialist' WHERE "EmployeeId"=8;
ALTER TABLE "Employee" ADD COLUMN salary decimal;
UPDATE "Employee" SET salary=CASE "EmployeeId" WHEN 8 THEN 75000.00 ELSE 50000.00 END;
COMMIT;

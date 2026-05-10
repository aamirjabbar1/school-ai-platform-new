from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from utils.password import hash_password
from sqlalchemy import select, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config.database import get_db
from middleware.auth import get_current_user, require_roles
from models.models import User, Notification
from services.teacher_import_service import (
    parse_salary_pdf,
    create_teacher_accounts,
    generate_credentials_excel,
)
from services.student_import_service import (
    parse_student_pdf,
    create_student_accounts,
    generate_student_credentials_excel,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class CreateUserRequest(BaseModel):
    name: str
    login_id: str
    email: str | None = None
    password: str
    role: str
    class_name: str | None = None
    subjects: list = []


class BulkCreateRequest(BaseModel):
    users: list[dict]


class BroadcastRequest(BaseModel):
    title: str
    message: str
    target_role: str | None = None


@router.get("/dashboard")
async def get_dashboard(
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        user_stats_sql = text("""
            SELECT
                COUNT(*) as total_users,
                COUNT(CASE WHEN role = 'student' THEN 1 END) as students,
                COUNT(CASE WHEN role = 'teacher' THEN 1 END) as teachers,
                COUNT(CASE WHEN role = 'admin' THEN 1 END) as admins,
                COUNT(CASE WHEN is_active = false THEN 1 END) as inactive_users
            FROM users
        """)
        result = await db.execute(user_stats_sql)
        user_stats = dict(result.mappings().first())

        content_stats_sql = text("""
            SELECT
                (SELECT COUNT(*) FROM documents) as total_documents,
                (SELECT COUNT(*) FROM documents WHERE is_ingested = true) as ingested_docs,
                (SELECT COUNT(*) FROM document_chunks) as total_chunks,
                (SELECT COUNT(*) FROM assignments WHERE is_active = true) as active_assignments,
                (SELECT COUNT(*) FROM submissions WHERE status = 'submitted') as pending_submissions,
                (SELECT COUNT(*) FROM question_papers) as question_papers
        """)
        result2 = await db.execute(content_stats_sql)
        content_stats = dict(result2.mappings().first())

        recent_sql = text("""
            SELECT * FROM (
                SELECT 'submission' as type, s.created_at as created_at, u.name as user_name, a.title as context
                FROM submissions s
                JOIN users u ON s.student_id = u.id
                JOIN assignments a ON s.assignment_id = a.id
                UNION ALL
                SELECT 'document' as type, d.created_at as created_at, u.name as user_name, d.title as context
                FROM documents d
                JOIN users u ON d.uploaded_by = u.id
            ) ORDER BY created_at DESC
            LIMIT 10
        """)
        result3 = await db.execute(recent_sql)
        recent = [dict(r) for r in result3.mappings().all()]

        return {"users": user_stats, "content": content_stats, "recent_activity": recent}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def get_users(
    role: str = None,
    is_active: str = None,
    search: str = None,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(User)
    if role:
        query = query.where(User.role == role)
    if is_active is not None:
        query = query.where(User.is_active == (is_active == "true"))
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                User.name.ilike(pattern),
                User.login_id.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    query = query.order_by(User.role, User.name)

    result = await db.execute(query)
    users = result.scalars().all()
    return [u.to_dict() for u in users]


@router.post("/users")
async def create_user(
    body: CreateUserRequest,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(User).where(User.login_id == body.login_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Login ID already exists")

    new_user = User(
        name=body.name, login_id=body.login_id,
        email=body.email or None,        # coerce "" → None to avoid UNIQUE collision
        password_hash=hash_password(body.password), role=body.role,
        class_name=body.class_name or None,
        subjects=body.subjects, is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user.to_dict()


@router.post("/users/bulk")
async def bulk_create_users(
    body: BulkCreateRequest,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    results = {"created": 0, "failed": []}
    for u_data in body.users:
        try:
            login_id = u_data.get("login_id")
            existing = await db.execute(select(User).where(User.login_id == login_id))
            if existing.scalar_one_or_none():
                results["failed"].append({"login_id": login_id, "reason": "Already exists"})
                continue

            new_user = User(
                name=u_data["name"], login_id=login_id,
                password_hash=hash_password(u_data.get("password", login_id)),
                role=u_data["role"], class_name=u_data.get("class_name"),
                subjects=u_data.get("subjects", []),
            )
            db.add(new_user)
            results["created"] += 1
        except Exception as e:
            results["failed"].append({"login_id": u_data.get("login_id"), "reason": str(e)})

    await db.commit()
    return results


@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    body: dict,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    password = body.pop("password", None)
    if password:
        target.password_hash = hash_password(password)

    for key, val in body.items():
        if hasattr(target, key) and key not in ("id", "password_hash", "created_at"):
            # Coerce empty strings to None for nullable unique columns
            if key == "email" and val == "":
                val = None
            setattr(target, key, val)

    await db.commit()
    await db.refresh(target)
    return target.to_dict()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Cannot delete own account")

    target.is_active = False
    await db.commit()
    return {"message": "User deactivated"}


@router.post("/broadcast")
async def broadcast_notification(
    body: BroadcastRequest,
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).where(User.is_active == True)
    if body.target_role:
        query = query.where(User.role == body.target_role)

    result = await db.execute(query)
    users = result.scalars().all()

    for u in users:
        db.add(Notification(user_id=u.id, title=body.title, message=body.message, type="announcement"))

    await db.commit()
    return {"message": f"Notification sent to {len(users)} users"}


# ─── TEACHER IMPORT FROM SALARY PDF ──────────────────────────────────────────

@router.post("/import-teachers")
async def import_teachers_from_pdf(
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload LSSP salary PDF -> parse teacher data -> create accounts ->
    return summary + downloadable credentials Excel.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    try:
        file_bytes = await file.read()

        # 1. Parse the salary PDF
        records = parse_salary_pdf(file_bytes)
        if not records:
            raise HTTPException(status_code=400, detail="No staff records found in PDF")

        # 2. Create accounts in database
        result = await create_teacher_accounts(records, db)

        # 3. Generate credentials Excel
        excel_bytes = generate_credentials_excel(result["created"], result["skipped"])

        # 4. Save the Excel file to uploads folder for download
        import os
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        excel_path = os.path.join(upload_dir, "teacher_credentials.xlsx")
        with open(excel_path, "wb") as f:
            f.write(excel_bytes)

        return {
            "message": f"Successfully processed {result['total']} records",
            "created": len(result["created"]),
            "skipped": len(result["skipped"]),
            "created_list": [
                {"name": r["name"].title(), "login_id": r["login_id"], "role": r["role"]}
                for r in result["created"]
            ],
            "skipped_list": [
                {"name": r["name"].title(), "reg_no": r["reg_no"], "reason": r.get("reason", "")}
                for r in result["skipped"]
            ],
            "download_url": "/api/admin/download-credentials",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/download-credentials")
async def download_credentials(
    user: User = Depends(require_roles("admin")),
):
    """Download the most recently generated credentials Excel file."""
    import os
    excel_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "uploads", "teacher_credentials.xlsx"
    )
    if not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail="No credentials file found. Import teachers first.")

    with open(excel_path, "rb") as f:
        content = f.read()

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=teacher_credentials.xlsx"},
    )


# ─── STUDENT IMPORT FROM PDF ─────────────────────────────────────────────────

@router.post("/import-students")
async def import_students_from_pdf(
    file: UploadFile = File(...),
    user: User = Depends(require_roles("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Upload student list PDF -> parse names -> create accounts -> return summary."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    try:
        file_bytes = await file.read()

        records = parse_student_pdf(file_bytes)
        if not records:
            raise HTTPException(status_code=400, detail="No student records found in PDF")

        result = await create_student_accounts(records, db)

        excel_bytes = generate_student_credentials_excel(result["created"], result["skipped"])

        import os
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        excel_path = os.path.join(upload_dir, "student_credentials.xlsx")
        with open(excel_path, "wb") as f:
            f.write(excel_bytes)

        return {
            "message": f"Processed {result['total']} student records",
            "created": len(result["created"]),
            "skipped": len(result["skipped"]),
            "created_list": [
                {"name": r["name"], "login_id": r["login_id"], "class": r.get("class_section", "")}
                for r in result["created"]
            ],
            "skipped_list": [
                {"name": r["name"], "class": r.get("class_section", ""), "reason": r.get("reason", "")}
                for r in result["skipped"]
            ],
            "download_url": "/api/admin/download-student-credentials",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/download-student-credentials")
async def download_student_credentials(
    user: User = Depends(require_roles("admin")),
):
    """Download student credentials Excel file."""
    import os
    excel_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "uploads", "student_credentials.xlsx"
    )
    if not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail="No credentials file found. Import students first.")

    with open(excel_path, "rb") as f:
        content = f.read()

    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=student_credentials.xlsx"},
    )

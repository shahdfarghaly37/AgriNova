# المرحلة 1 — الباك إند

انسخ الملفات دي جوه فولدر `NASA/NASA` (جنب 09_engine.py) وانت موافق على استبدال config.py.

## التشغيل
    pip install -r requirements.txt
    python test_api.py            # اختبار سريع
    uvicorn api:app --reload --port 8000
    # ادخل على http://localhost:8000/docs لتجربة الـ endpoints

## الـ endpoints
- GET /api/governorates          27 محافظة (للقايمة)
- GET /api/crops                 المحاصيل اللي يقدر يسأل عنها
- GET /api/top?gov=gharbia&n=3   الفيتشر 1: أنسب محاصيل
- GET /api/check?gov=gharbia&crop=قمح   الفيتشر 2: ينفع ولا لأ + البديل + الانتظار
- GET /api/climate?gov=gharbia   الفيتشر 3: المناخ + اللي يتزرع دلوقتي

## محافظات زيادة (إنترنت مطلوب)
    python add_governorate.py cairo
    python add_governorate.py --all
بتحمّل بيانات NASA POWER الحقيقية وتضيفها. من غيرها المحافظة بتستخدم أقرب محطة من الـ10.

## ملاحظات
- كل الكلام العربي في egypt.py، عدّل فيه براحتك.
- الإنتاجية تقدير تجريبي (الموديل متدرب على داتا غير موثقة) وده مكتوب في الـ API.
- المحاصيل غير الخمسة الأساسية (عنب، برتقال...) تقدير من الجو بس وعليها علامة limited.

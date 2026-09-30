# ruff: noqa: E501
"""Extra published briefs for the dev database. Not part of the test fixture.

The copy is original desk text written for this seed. It is not taken from Wikipedia
or any other article.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsroom.articles.models import ArticleLocalization, Author
from newsroom.articles.schemas import ArticleCreate, ArticleType, LocalizationCreate
from newsroom.articles.service import ArticleService
from newsroom.seed.demo import _content, _principal, _section, _walk

# section key, English tail, Arabic tail, then (slug, English title, Arabic title).
_SECTIONS: tuple[tuple[str, str, str, str, str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "politics",
        "Politics",
        "سياسة",
        "siyasa",
        "The item is a demo brief filed so the public list and the desk can turn a page.",
        "هذه نشرة تجريبية كُتبت لهذا الموقع حتى تمتلئ القوائم وصفحات الأقسام.",
        (
            ("council-delays-zoning", "City council delays the zoning vote", "المجلس يؤجل تصويت التنظيم"),
            ("night-bus-contract", "Transit agency extends the night-bus contract", "النقل يمدد عقد الحافلات الليلية"),
            ("harbor-lease-review", "Port board reopens the harbor lease", "الميناء يعيد فتح عقد الرصيف"),
            ("school-calendar-vote", "School board holds the calendar vote", "التعليم يُبقي تصويت التقويم"),
            ("park-curfew-hearing", "Parks department hears the curfew appeal", "الحدائق تستمع إلى طعن حظر التجول"),
            ("library-hours-draft", "Libraries publish a draft of winter hours", "المكتبات تنشر مسودة ساعات الشتاء"),
            ("water-main-repair", "Crews start the water-main repair", "الفرق تبدأ إصلاح الخط الرئيسي"),
            ("ballot-drop-boxes", "Election office adds two drop boxes", "الانتخابات تضيف صندوقين للإيداع"),
            ("overtime-report-filed", "Police file the quarterly overtime report", "الشرطة تودع تقرير العمل الإضافي"),
            ("permit-queue-shortens", "Housing desk shortens the permit queue", "الإسكان يقصّر طابور الرخص"),
            ("river-path-funding", "Council sets aside funds for the river path", "المجلس يرصد مبلغاً لممر النهر"),
            ("clinic-hours-cut", "The evening clinic drops one weeknight", "العيادة المسائية تلغي ليلة"),
            ("snow-route-map", "Public works posts the snow-route map", "الأشغال تنشر خريطة مسارات الثلج"),
            ("ethics-memo-circulated", "The ethics office circulates a short memo", "مكتب السلوك يعمّم مذكرة قصيرة"),
            ("ferry-fare-proposal", "The ferry operator proposes a fare table", "المشغّل يقترح جدول أجور العبّارة"),
            ("landfill-hearing-set", "A hearing date is set for the landfill plan", "يُحدد موعد جلسة خطة المكب"),
            ("streetlight-pilot", "Six streets join the streetlight pilot", "ست شوارع تدخل تجربة الإنارة"),
            ("census-tract-note", "The statistics office updates one tract note", "الإحصاء يحدّث ملاحظة حي واحد"),
            ("fire-station-site", "Fire service names a preferred station site", "الإطفاء يسمي موقعاً مفضلاً للمركز"),
            ("comment-window-open", "A two-week public comment window opens", "تُفتح نافذة تعليقات لأسبوعين"),
        ),
    ),
    (
        "sports",
        "Sports",
        "رياضة",
        "riyada",
        "The item is a demo sports brief, written for the seed and not taken from a match report.",
        "هذه نشرة رياضية تجريبية كُتبت للبذرة، وليست منقولة من تقرير مباراة.",
        (
            ("derby-ends-level", "The derby ends level after a late equalizer", "الديربي ينتهي بالتعادل بهدف متأخر"),
            ("marathon-route-change", "Organizers shorten the marathon by one loop", "المنظمون يقصّرون الماراثون لفة"),
            ("swim-relay-record", "The relay team lowers the club record", "فريق التتابع يخفض رقم النادي"),
            ("coach-leaves-bench", "The head coach leaves the bench next month", "المدرب يغادر الدكة الشهر المقبل"),
            ("youth-league-final", "The youth final is fixed for Sunday noon", "نهائي الناشئين يُثبت ظهر الأحد"),
            ("pitch-drainage-fix", "Ground staff finish the pitch drainage", "العمال ينهون تصريف أرض الملعب"),
            ("away-stand-closed", "The away stand stays closed for one match", "مدرج الضيوف يُغلق لمباراة واحدة"),
            ("keeper-injury-update", "The keeper is out for the next two fixtures", "الحارس يغيب عن المباراتين التاليتين"),
            ("track-meet-postponed", "Rain postpones the afternoon track meet", "المطر يؤجل اجتماع ألعاب القوى"),
            ("rowing-club-title", "The rowing club keeps the regional title", "نادي التجديف يحتفظ بلقب المنطقة"),
            ("stage-neutralized", "Officials neutralize the final cycling stage", "الحكام يحيّدون المرحلة الأخيرة"),
            ("referee-crew-named", "The referee crew for the final is named", "تُعلن طاقم تحكيم النهائي"),
            ("winter-classic-full", "The winter classic is sold out", "الكلاسيكو الشتوي تُباع تذاكره"),
            ("training-camp-opens", "The training camp opens on the coast", "المعسكر يُفتح على الساحل"),
            ("window-stays-quiet", "The club confirms a quiet registration window", "النادي يؤكد نافذة تسجيل هادئة"),
            ("court-resurfacing", "The main court reopens after resurfacing", "الملعب الرئيسي يُفتح بعد التجديد"),
            ("under-21-call-up", "Two players join the under-21 list", "لاعبان يلتحقان بقائمة تحت 21"),
            ("ceremony-delayed", "The medal ceremony waits for the photo finish", "حفل الميداليات ينتظر صورة النهاية"),
            ("fixture-list-out", "The spring fixture list is released", "تُنشر قائمة مباريات الربيع"),
            ("goal-line-check", "The goal-line check confirms the score", "فحص خط المرمى يؤكد النتيجة"),
        ),
    ),
    (
        "economy",
        "Economy",
        "اقتصاد",
        "iqtisad",
        "The item is a demo business brief written for this newsroom, not a market wire.",
        "هذه نشرة اقتصادية تجريبية كُتبت لهذه الغرفة، وليست برقية أسواق.",
        (
            ("port-throughput-rises", "The port handles more containers this week", "الميناء يتداول حاويات أكثر هذا الأسبوع"),
            ("bakery-wheat-note", "Bakeries note a steadier wheat delivery", "المخابز تلاحظ استقرار توريد القمح"),
            ("workshop-shifts-added", "The workshop adds a Saturday shift", "الورشة تضيف وردية السبت"),
            ("market-stall-fees", "The market board freezes stall fees", "السوق يجمّد رسوم البسطات"),
            ("credit-union-branch", "The credit union opens a branch by the station", "الجمعية تفتح فرعاً قرب المحطة"),
            ("freight-delay-note", "Freight desks warn of a one-day delay", "الشحن ينبّه إلى تأخير يوم واحد"),
            ("harvest-forecast-cut", "The harvest forecast is trimmed after dry weeks", "توقّع الحصاد يُخفض بعد أسابيع جافة"),
            ("wage-talks-resume", "Wage talks resume after a short pause", "مباحثات الأجور تُستأنف بعد توقف قصير"),
            ("shop-hours-extended", "Corner shops extend evening hours", "الدكاكين تمدد ساعات المساء"),
            ("fuel-depot-check", "Inspectors finish the fuel-depot check", "المفتشون ينهون فحص مستودع الوقود"),
            ("textile-order-book", "The textile mill shows a fuller order book", "المصنع يعرض دفتراً أكمل للطلبات"),
            ("rent-index-posted", "The rent index for the quarter is posted", "يُنشر مؤشر الإيجار للربع"),
            ("coop-dividend-set", "The cooperative sets a modest dividend", "الجمعية تحدد أرباحاً متواضعة"),
            ("customs-queue-shorter", "The customs hall reports a shorter queue", "الجمارك تبلغ عن طابور أقصر"),
            ("mill-reopens-line", "The mill reopens one packing line", "المطحنة تعيد فتح خط تعبئة"),
            ("bookings-dip", "Tour desks report a dip in midweek bookings", "مكاتب السياحة تبلغ عن تراجع منتصف الأسبوع"),
            ("invoice-reminder", "Firms are reminded of the new invoice line", "تُذكَّر الشركات بسطر الفاتورة الجديد"),
            ("warehouse-lease", "A logistics firm signs the warehouse lease", "شركة لوجستية توقع عقد المستودع"),
            ("shop-survey-out", "A survey of corner shops is published", "يُنشر مسح للدكاكين"),
            ("silo-capacity", "The grain silo is listed at higher capacity", "تُدرج الصومعة بسعة أعلى"),
        ),
    ),
    (
        "science",
        "Science",
        "علوم",
        "ulum",
        "The item is a demo science brief written for this seed, not a paper abstract.",
        "هذه نشرة علمية تجريبية كُتبت لهذه البذرة، وليست ملخص بحث.",
        (
            ("tide-gauge-repaired", "Technicians repair the harbor tide gauge", "الفنيون يصلحون مقياس المد في الميناء"),
            ("owl-count-posted", "Volunteers post the winter owl count", "المتطوعون ينشرون عدّ البوم الشتوي"),
            ("lab-open-afternoon", "The teaching lab holds an open afternoon", "المختبر التعليمي يفتح بعد الظهر"),
            ("glacier-photos-filed", "The archive files a new set of glacier photos", "الأرشيف يودع مجموعة صور للجليد"),
            ("well-sample-clear", "The latest well sample comes back clear", "عينة البئر الأخيرة تعود صافية"),
            ("meteor-watch-set", "The observatory sets a meteor-watch night", "المرصد يحدد ليلة لرصد الشهب"),
            ("seed-bank-deposit", "The seed bank accepts a new deposit", "بنك البذور يقبل إيداعاً جديداً"),
            ("reef-survey-boat", "The survey boat leaves for the reef", "قارب المسح يغادر نحو الشعاب"),
            ("pollen-count-high", "The pollen count stays high through Friday", "عدّ اللقاح يبقى مرتفعاً حتى الجمعة"),
            ("mirror-cleaned", "Staff clean the telescope mirror overnight", "الفريق ينظّف مرآة التلسكوب ليلاً"),
            ("soil-map-revised", "Cartographers revise one soil map", "رسامو الخرائط يراجعون خريطة تربة"),
            ("bat-roost-logged", "Rangers log a new bat roost", "الحراس يسجلون مجثماً جديداً للخفافيش"),
            ("comet-chart-posted", "The comet chart for the month is posted", "يُنشر مخطط المذنب لهذا الشهر"),
            ("clinic-slot-card", "The clinic posts the week's slot card", "العيادة تنشر بطاقة مواعيد الأسبوع"),
            ("oxygen-reading", "The river station records a steadier oxygen reading", "محطة النهر تسجل قراءة أكسجين أثبت"),
            ("fossil-label-fixed", "The museum corrects one fossil label", "المتحف يصحح بطاقة أحفورة"),
            ("antenna-test", "Engineers run a short antenna-array test", "المهندسون يجرون اختباراً قصيراً للهوائيات"),
            ("drought-monitor", "The drought monitor adds a caution note", "مرصد الجفاف يضيف ملاحظة حذر"),
            ("band-returned", "A banded bird is reported two valleys away", "يُبلغ عن طائر مُحلَّق على بعد واديين"),
            ("eclipse-card", "The planetarium prints the eclipse timing card", "القبة الفلكية تطبع بطاقة توقيت الخسوف"),
        ),
    ),
    (
        "culture",
        "Culture",
        "ثقافة",
        "thaqafa",
        "The item is a demo culture brief written for this seed, not a review copied from elsewhere.",
        "هذه نشرة ثقافية تجريبية كُتبت لهذه البذرة، وليست مراجعة منقولة.",
        (
            ("poetry-night-lineup", "The poetry night announces its lineup", "أمسية الشعر تعلن أسماء المشاركين"),
            ("archive-film-screen", "The archive screens a restored short film", "الأرشيف يعرض فيلماً قصيراً مرمماً"),
            ("ceramic-fair-opens", "The ceramic fair opens in the old hall", "معرض الخزف يُفتح في القاعة القديمة"),
            ("choir-tour-dates", "The choir publishes three tour dates", "الجوقة تنشر ثلاثة مواعيد للجولة"),
            ("mural-permit", "The mural on the side street gets its permit", "الجدارية في الشارع الجانبي تحصل على الرخصة"),
            ("novel-shortlist", "The novel prize publishes a shortlist of six", "جائزة الرواية تنشر قائمة من ستة"),
            ("theatre-roof", "The theatre closes one week for the roof", "المسرح يُغلق أسبوعاً للسقف"),
            ("folk-rehearsal", "The folk troupe rehearses for the square", "الفرقة الشعبية تتدرب للساحة"),
            ("photo-show-extended", "The photo exhibit stays up another week", "معرض الصور يبقى أسبوعاً إضافياً"),
            ("story-hour", "The children's story hour moves to Saturday", "ساعة القصة للأطفال تنتقل إلى السبت"),
            ("guest-conductor", "A guest conductor leads one concert", "قائد ضيف يقود حفلة واحدة"),
            ("press-museum-hours", "The press museum changes its Sunday hours", "متحف الصحافة يغيّر ساعات الأحد"),
            ("calligraphy-class", "The calligraphy workshop adds an evening class", "ورشة الخط تضيف حصة مسائية"),
            ("festival-gates", "Festival gates open an hour earlier", "بوابات المهرجان تُفتح قبل ساعة"),
            ("radio-play", "The radio play premieres on Thursday night", "التمثيلية الإذاعية تُعرض ليل الخميس"),
            ("quilt-judges", "The quilt show names its judges", "معرض الأغطية يسمي أعضاء اللجنة"),
            ("author-visit", "A novelist visits the branch library", "روائية تزور مكتبة الفرع"),
            ("floor-refinished", "The dance floor is refinished before the season", "أرضية الرقص تُجدد قبل الموسم"),
            ("subtitle-note", "The subtitle desk notes a shorter credit roll", "مكتب الترجمة يلاحظ شارة أقصر"),
            ("gallery-wall", "The gallery changes the wall for new prints", "المعرض يغيّر الجدار لمطبوعات جديدة"),
        ),
    ),
)


async def seed_volume(db: AsyncSession) -> list[str]:
    """Publish about 100 original briefs. Skips any slug already in the database."""
    present = set(
        (await db.scalars(select(ArticleLocalization.slug))).all()
    )
    writer = await _principal(db, "demo-writer@example.com")
    super_admin = await _principal(db, "demo-super@example.com")
    copy_editor = await _principal(db, "demo-copy@example.com")
    author = await db.scalar(select(Author).where(Author.user_id == writer.user.id))
    if author is None:
        raise RuntimeError("demo writer has no author profile")
    articles = ArticleService(db)
    added = 0
    section_ids = {
        "politics": await _section(db, "politics", ("ar", "سياسة", "siyasa"), ("en", "Politics", "politics")),
        "sports": await _section(db, "sports", ("ar", "رياضة", "riyada"), ("en", "Sports", "sports")),
        "economy": await _section(db, "economy", ("ar", "اقتصاد", "iqtisad"), ("en", "Economy", "economy")),
        "science": await _section(db, "science", ("ar", "علوم", "ulum"), ("en", "Science", "science")),
        "culture": await _section(db, "culture", ("ar", "ثقافة", "thaqafa"), ("en", "Culture", "culture")),
    }
    for key, _en_name, _ar_name, _slug, en_tail, ar_tail, pairs in _SECTIONS:
        for slug, en_title, ar_title in pairs:
            if slug in present:
                continue
            created = await articles.create(
                writer,
                ArticleCreate(
                    section_id=section_ids[key],
                    article_type=ArticleType.NEWS,
                    author_ids=[author.id],
                    locale="en",
                    slug=slug,
                    content=_content(en_title, en_title, en_title + ".", en_tail),
                ),
            )
            english = next(item for item in created.localizations if item.locale == "en")
            await _walk(articles, writer, super_admin, copy_editor, english.id, english.lock_version)
            await articles.add_localization(
                writer,
                created.id,
                LocalizationCreate(
                    locale="ar",
                    slug=f"{slug}-ar",
                    content=_content(ar_title, ar_title, ar_title + ".", ar_tail),
                ),
            )
            refreshed = await articles.get_admin(super_admin, created.id)
            arabic = next(item for item in refreshed.localizations if item.locale == "ar")
            await _walk(articles, writer, super_admin, copy_editor, arabic.id, arabic.lock_version)
            present.add(slug)
            added += 1
    if added == 0:
        return ["demo briefs already present"]
    return [f"published {added} demo briefs across five desks"]

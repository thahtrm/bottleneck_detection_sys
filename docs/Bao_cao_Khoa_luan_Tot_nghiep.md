# BÁO CÁO KHÓA LUẬN TỐT NGHIỆP
## HỆ THỐNG MÁY HỌC DỰ ĐOÁN NGUY CƠ TRỄ HẠN VÀ ĐỊNH LƯỢNG MỨC ĐỘ TRỌNG YẾU TÁC VỤ TRONG QUẢN TRỊ DỰ ÁN PHẦN MỀM

---

# CHƯƠNG 2: DỮ LIỆU NGHIÊN CỨU VÀ QUY TRÌNH TIỀN XỬ LÝ

## 2.1. TỔNG QUAN VÀ NGUỒN GỐC TẬP DỮ LIỆU

### 2.1.1. Nguồn gốc và xuất xứ tập dữ liệu (Data Provenance)

Để giải quyết bài toán dự đoán rủi ro trễ hạn nhiệm vụ phần mềm và phân tích độ trọng yếu của công việc trong các dự án thực tế, nghiên cứu này sử dụng kho dữ liệu **The Public Jira Dataset** được công bố bởi nhóm tác giả Montgomery, Lüders và Maalej tại Hội nghị Quốc tế về Khai phá Kho Phần mềm (*IEEE/ACM International Conference on Mining Software Repositories - MSR 2022*). Tập dữ liệu được lưu trữ và chia sẻ chính thức trên kho lưu trữ khoa học Zenodo theo giấy phép bản quyền mở Creative Commons Attribution 4.0 International (CC-BY-4.0).

Kho dữ liệu này ghi nhận quá trình vận hành, phát triển và tương tác phần mềm xuyên suốt hơn hai thập kỷ (giai đoạn từ 2001 đến 2022) từ **16 hệ sinh thái phần mềm lớn trên thế giới**, bao gồm cả các tổ chức mã nguồn mở quy mô cộng đồng lẫn các dự án phần mềm thương mại công nghiệp:
- **Tập đoàn & Dự án quốc tế**: *Apache Software Foundation, Atlassian Jira, Mojang (Minecraft), Spring Framework, RedHat, MongoDB, Qt Project, JFrog, MariaDB, Sonatype, Hyperledger, Sakai, IntelDAOS, JiraEcosystem, Mindville, SecondLife*.
- **Tính pháp lý và ẩn danh (Anonymization)**: Nhằm tuân thủ các quy chuẩn đạo đức nghiên cứu và bảo vệ quyền riêng tư, toàn bộ định danh cá nhân (như tài khoản người tạo `reporter`, người thực hiện `assignee`, người bình luận `author`) đã được làm mờ thông qua việc mã hóa sang chuỗi UUID4 ẩn danh dạng chuẩn (`<<|author_name|<uuid>|>>`), đảm bảo phân biệt được hành vi độc lập của từng kỹ sư nhưng không làm lộ danh tính thực tế.

---

### 2.2. KIẾN TRÚC VÀ MÔ HÌNH DỮ LIỆU

### 2.2.1. Quy mô và cấu trúc mô hình dữ liệu (Data Topology & Schema)

Toàn bộ dữ liệu thô sau quá trình trích xuất và chuyển đổi (ETL) được tổ chức lưu trữ và truy vấn hiệu năng cao thông qua cơ sở dữ liệu phân tích hiện đại DuckDB. Tập dữ liệu bao gồm 4 thực thể quan hệ trung tâm được mô tả trực quan tại Hình 3.1.

![Hình 3.1: Sơ đồ Kiến trúc và Quan hệ Thực thể Tập dữ liệu Quản lý Dự án Jira](figures/data_topology_schema.png)

#### Bảng 3.1: Tổng hợp quy mô các thực thể trong tập dữ liệu nghiên cứu
| Thực thể dữ liệu | Bảng lưu trữ | Số lượng bản ghi | Ý nghĩa nghiệp vụ trong quản lý dự án |
| :--- | :--- | :---: | :--- |
| **Nhiệm vụ (Issues)** | `jira_issues` | **2,685,911** | Đơn vị tác vụ công việc cơ bản (Bug, Feature, Task, Improvement...) |
| **Nhật ký biến động (Changelogs)** | `issue_changelogs` | **31,784,341** | Lịch sử vết chuyển dịch trạng thái, tái gán người xử lý, đổi hạn chót |
| **Bình luận kỹ thuật (Comments)** | `issue_comments` | **8,850,755** | Tương tác thảo luận, trao đổi giải pháp giữa các kỹ sư và kiểm thử viên |
| **Liên kết phụ thuộc (Issue Links)** | `issue_links` | **> 1,000,000** | Cạnh đồ thị biểu thị quan hệ phụ thuộc (*Blocks*, *Depends on*, *Subtask*) |

---

### 2.2.2. Mô tả các thuộc tính đặc trưng cốt lõi (Data Attributes)

Mỗi bản ghi tác vụ (Issue) mang các nhóm thuộc tính phản ánh bối cảnh công việc tại thời điểm khởi tạo và trong suốt vòng đời thực thi:

#### Bảng 3.2: Danh mục các trường dữ liệu chính của một Issue
| Tên trường dữ liệu | Kiểu dữ liệu | Ý nghĩa và mô tả nghiệp vụ |
| :--- | :---: | :--- |
| `issue_key` | `VARCHAR` | Khóa chính định danh duy nhất cho từng nhiệm vụ (Ví dụ: `SPR-12345`, `LUCENE-4321`). |
| `project_key` | `VARCHAR` | Mã định danh dự án / phân hệ phần mềm mà nhiệm vụ trực thuộc. |
| `issue_type` | `VARCHAR` | Thể loại công việc: *Bug, New Feature, Improvement, Task, Sub-task*. |
| `created_ts` | `TIMESTAMP` | Thời điểm chính xác tác vụ được khởi tạo và đưa vào backlog hệ thống. |
| `resolved_ts` | `TIMESTAMP` | Thời điểm nhiệm vụ hoàn tất và chuyển sang trạng thái kết thúc (*Closed / Resolved*). |
| `priority` | `VARCHAR` | Mức độ ưu tiên kỹ thuật được gán (*Blocker, Critical, Major, Minor, Trivial*). |
| `assignee` | `VARCHAR` | Mã định danh ẩn danh của kỹ sư chịu trách nhiệm thực thi trực tiếp nhiệm vụ. |
| `reporter` | `VARCHAR` | Mã định danh ẩn danh của thành viên phát hiện và tạo thẻ nhiệm vụ. |
| `summary` & `description` | `TEXT` | Tiêu đề tóm tắt và mô tả chi tiết yêu cầu kỹ thuật bằng ngôn ngữ tự nhiên. |
| `resolution` | `VARCHAR` | Kết quả xử lý cuối cùng: *Fixed, Won't Fix, Duplicate, Incomplete, Not a Bug*. |
| `story_points` | `INTEGER` | Độ phức tạp ước tính của tác vụ theo quy chuẩn Agile (nếu có ghi nhận). |
| `planned_duration_days` | `FLOAT` | Thời gian hoàn thành dự kiến ban đầu được cam kết theo kế hoạch. |

---

### 2.2.3. Định nghĩa biến mục tiêu (Target Variable Definition)

Trong nghiên cứu này, bài toán trọng tâm là dự đoán sớm nguy cơ chậm trễ tiến độ của một nhiệm vụ phần mềm. Biến mục tiêu $y \in \{0, 1\}$ (`is_delayed`) là một biến nhị phân được xác định toán học như sau:

$$y_i = \begin{cases} 
1 & \text{nếu } t_{\text{actual\_duration}}^{(i)} > t_{\text{planned\_duration}}^{(i)} \quad \text{(Bị trễ hạn)} \\ 
0 & \text{ngược lại} \quad \text{(Hoàn thành đúng hạn hoặc sớm hạn)} 
\end{cases}$$

Trong đó:
- $t_{\text{actual\_duration}}^{(i)} = t_{\text{resolved\_ts}}^{(i)} - t_{\text{created\_ts}}^{(i)}$ là tổng thời lượng thực tế từ lúc khởi tạo đến lúc hoàn tất nhiệm vụ.
- $t_{\text{planned\_duration}}^{(i)}$ là thời gian kỳ vọng được xác định từ mốc hạn chót (`due_date`) hoặc ước tính theo năng lực lịch sử của đội ngũ phát triển tại thời điểm giao việc.

---

### 2.2.4. Thống kê mô tả và các thách thức đặc thù của dữ liệu (Data Characteristics & Challenges)

Qua quá trình phân tích khám phá dữ liệu (Exploratory Data Analysis - EDA), đề tài ghi nhận các đặc trưng thống kê và thách thức nghiên cứu then chốt:

![Hình 3.2: Hiện tượng Dịch chuyển Phân phối Tỷ lệ Trễ theo Thời gian (Temporal Prior Shift)](figures/temporal_prior_shift.png)

1. **Hiện tượng Dịch chuyển Phân phối theo Thời gian (Temporal Prior Shift)**:
   - Tỷ lệ mẫu dương (`is_delayed = 1`) có xu hướng sụt giảm mạnh theo thời gian, từ $39.68\%$ trong giai đoạn lịch sử (Train) xuống còn $21.68\%$ trong giai đoạn gần đây (Test) như thể hiện ở Hình 3.2.
   - Sự dịch chuyển này phản ánh sự biến đổi trong quy trình quản lý của các tổ chức, yêu cầu các mô hình máy học phải có khả năng thích ứng ngưỡng phân loại (threshold calibration), tránh việc kích hoạt quá nhiều cảnh báo giả.
2. **Sự bùng nổ của Tác vụ Ảo (Non-Work / Invalid Tasks)**:
   - Trong các hệ sinh thái phần mềm lớn (đặc biệt là các dự án cộng đồng mở), tỷ lệ các tác vụ không tạo ra giá trị kỹ thuật thực thụ chiếm tới $38.50\%$ – $51.49\%$ trong tập kiểm thử gần đây. Các tác vụ này bao gồm: lỗi trùng lặp (`Duplicate` - $22.98\%$), không phải lỗi (`Not a Bug` / `Cannot Reproduce` - $12.76\%$), hoặc từ chối xử lý (`Won't Fix` - $11.04\%$). 
   - Nếu không có cơ chế tiền lọc (Pre-triage filtering), các tác vụ này sẽ đóng vai trò là "nhiễu nghiêm trọng", khiến mô hình nhận định sai lệch về năng suất của kỹ sư.
3. **Bài toán Dữ liệu Kiểm duyệt Phải (Right-Censored Issues)**:
   - Tại thời điểm cắt dữ liệu, có hơn $195,422$ nhiệm vụ vẫn đang trong trạng thái xử lý dở dang (`is_resolved = 0`). Việc tùy tiện loại bỏ các mẫu này sẽ gây ra hiện tượng *Chệch lựa chọn sống sót (Survivorship Bias)*. Đề tài áp dụng các kỹ thuật phân tích sinh tồn (Survival Analysis) để tận dụng các mẫu kiểm duyệt này một cách trọn vẹn.

---

### 2.5. CHIẾN LƯỢC PHÂN CHIA DỮ LIỆU THỰC NGHIỆM (STRICT CHRONOLOGICAL SPLIT)

### 2.5.1. Chiến lược phân chia dữ liệu thực nghiệm (Strict Chronological Split)

Trong phân tích dự đoán tiến độ phần mềm, việc chia ngẫu nhiên (Random K-Fold Cross Validation) sẽ dẫn đến sai số nghiêm trọng do **Rò rỉ Dữ liệu Thời gian (Temporal Data Leakage)** — mô hình vô tình học các tri thức từ tương lai để dự đoán cho quá khứ. 

Để đảm bảo tính khách quan và khả năng triển khai thực tế, nghiên cứu áp dụng nguyên tắc **Zero Temporal Data Leakage**, thực hiện phân chia tuần tự theo trục thời gian tạo nhiệm vụ (`created_ts`):

#### Bảng 3.3: Thiết lập phân vùng dữ liệu phục vụ huấn luyện và kiểm thử
| Phân vùng dữ liệu | Định dạng tệp lưu trữ | Số lượng Issues | Tỷ lệ trễ (`is_delayed = 1`) | Khung thời gian | Vai trò trong quy trình thực nghiệm |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **Tập Huấn luyện (Train)** | `data/train.parquet` | **1,615,472** | **39.68%** | 2001 – 2018 | Khớp các tham số tiền xử lý và huấn luyện các mô hình phân loại cơ sở. |
| **Tập Kiểm duyệt (Train Censored)** | `data/train_censored.parquet` | **1,810,894** | *Dữ liệu sinh tồn* | 2001 – 2018 | Bổ sung 195,422 task chưa kết thúc để huấn luyện mô hình sinh tồn (Cox/AFT). |
| **Tập Tinh chỉnh (Validation)** | `data/val.parquet` | **346,172** | **33.90%** | 2018 – 2020 | Tinh chỉnh siêu tham số (Hyperparameter Tuning) và quét ngưỡng phân loại tối ưu $T^*$. |
| **Tập Kiểm thử Mù (Out-of-Time Test)** | `data/test.parquet` | **346,174** | **21.68%** | 2020 – 2022 | Đóng băng để đánh giá hiệu năng độc lập, phản ánh năng lực dự đoán tương lai thực tế. |

---

### 2.5.2. Tóm tắt tiểu mục

Tập dữ liệu The Public Jira Dataset với hơn 2.68 triệu tác vụ và hàng chục triệu bản ghi tương tác là nguồn tri thức phong phú, phản ánh chân thực các quy luật vận hành và rủi ro chậm trễ trong các dự án phần mềm hiện đại. Việc phân chia dữ liệu bất biến theo thời gian (Strict Chronological Split) và nhận diện sớm các thách thức về dịch chuyển phân phối, dữ liệu kiểm duyệt và tác vụ ảo là tiền đề then chốt để xây dựng quy trình tiền xử lý và kỹ nghệ đặc trưng (Feature Engineering) khoa học ở các phần tiếp theo của báo cáo.


---

## 2.3. TRÍCH XUẤT VÀ NẠP DỮ LIỆU (ETL PIPELINE)

### 2.3.1. Bối cảnh và Thách thức Kỹ thuật
Kho dữ liệu gốc *The Public Jira Dataset* được công bố dưới dạng các tệp sao lưu (data dump) của cơ sở dữ liệu hướng tài liệu MongoDB (database `JiraReposAnon`). Trong đó, mỗi hệ sinh thái phần mềm (instance) là một tập hợp (collection) độc lập chứa hàng trăm nghìn đến hàng triệu tài liệu định dạng BSON với tổng dung lượng vượt quá **60 GB**.

Trong các thử nghiệm ban đầu, việc đọc dữ liệu trực tiếp từ MongoDB thông qua trình điều khiển Python gặp phải ba rào cản kỹ thuật nghiêm trọng:
1. **Hiện tượng Tràn bộ nhớ (Out-Of-Memory - OOM)**: Với các hệ sinh thái quy mô lớn như *Mojang* (421,000 issues, ~20 GB thô) hay *Apache* (>1,000,000 issues), việc chuyển đổi đồng loạt các tài liệu BSON lồng nhau phức tạp thành danh sách đối tượng Python trong RAM làm dung lượng bộ nhớ bùng nổ vượt quá 32–50 GB, gây sập tiến trình.
2. **Chi phí duy trì tiến trình nền**: Việc vận hành liên tục một tiến trình `mongod` chiếm dụng tài nguyên hệ thống và cổng mạng không phù hợp với các đường ống thử nghiệm tự động (CI/CD) và môi trường huấn luyện mô hình phân tán.
3. **Hiệu năng xử lý phân tích (OLAP) hạn chế**: MongoDB tối ưu cho các thao tác đọc/ghi giao dịch theo dòng (OLTP), nhưng tỏ ra kém hiệu quả khi thực hiện các phép toán tổng hợp theo cột (columnar aggregation), tính toán cửa sổ trượt theo thời gian (time-series rolling window), và trích xuất đặc trưng mạng đồ thị.

Nhằm giải quyết triệt để các rào cản trên, nghiên cứu đã tái cấu trúc toàn diện tầng dữ liệu, chuyển dịch từ MongoDB sang hệ cơ sở dữ liệu phân tích dạng cột nhúng **DuckDB** (`data/jira.duckdb`).

![Hình 2.1: Kiến trúc Pipeline Streaming ETL từ MongoDB sang DuckDB](figures/etl_pipeline_architecture.png)

### 2.3.2. Kiến trúc Đường ống Dữ liệu (Streaming Chunk-based ETL Architecture)
Để triệt tiêu nguy cơ tràn bộ nhớ, đường ống ETL được thiết kế theo cơ chế dòng chảy phân đoạn (**Streaming Chunk-based Processing**) với kích thước lô cố định $\text{batch\_size} = 5,000$ documents, đảm bảo mức tiêu thụ bộ nhớ RAM luôn là hằng số $O(\text{batch}) \approx 250\text{MB} - 400\text{MB}$ trong suốt vòng đời xử lý.

Đường ống bao gồm 3 pha kế tiếp nhau (Hình 2.1):

#### 1. Pha Trích xuất (Extract Phase)
Thành phần `MongoStreamExtractor` thiết lập con trỏ máy chủ (server cursor) kết nối tới MongoDB với tham số `no_cursor_timeout = True`. Dữ liệu được đọc tuần tự theo từng khối (chunk) $5,000$ tài liệu mà không nạp toàn bộ tập hợp vào bộ nhớ, đảm bảo tiến trình trích xuất ổn định ngay cả với tập dữ liệu hàng triệu bản ghi.

#### 2. Pha Chuyển đổi và Chuẩn hóa (Transform Phase)
Mỗi tài liệu BSON lồng nhau phức tạp được chuẩn hóa và phân rã cấu trúc thông qua hàm `normalize_doc()`:
- **Phẳng hóa cấu trúc quan hệ**: Tách một tài liệu Issue nguyên khối thành 4 bảng quan hệ phẳng độc lập:
  - `issues`: Chứa thông tin định danh, thuộc tính kỹ thuật, thời gian và kết quả xử lý.
  - `issue_changelogs`: Bóc tách lịch sử các sự kiện biến động trạng thái (`status`), người nhận việc (`assignee`), độ ưu tiên (`priority`).
  - `issue_comments`: Trích xuất dòng thời gian các thảo luận kỹ thuật phục vụ phân tích ngôn ngữ tự nhiên.
  - `issue_links`: Chuẩn hóa các quan hệ phụ thuộc có hướng giữa các cặp nhiệm vụ.
- **Xử lý dị thường thời gian**: Phát hiện và xử lý các mốc thời gian placeholder bị lỗi (ví dụ: các mốc ngày `1969-12-31T16:00:00` ở các issue `IDE-*` của Spring) bằng cách kẹp (clamp) giá trị timestamp âm về mốc epoch 0, ngăn ngừa lỗi tràn số nguyên khi tính toán độ trễ thời gian.
- **Chuẩn hóa nhãn và danh mục**: Loại bỏ tiền tố số trong chuỗi mức độ ưu tiên (ví dụ: chuyển `"4 - Normal"` về `"Normal"`), gộp các quan hệ chặn và phụ thuộc tương đương (*Blocks / Depends on*).

#### 3. Pha Nạp dữ liệu (Load Phase)
Thành phần `DuckDBLoader` tiếp nhận dữ liệu đã được chuẩn hóa và nạp vào tệp cơ sở dữ liệu `data/jira.duckdb`:
- **Giao tác nguyên tử (Transaction per chunk)**: Mỗi khối 5,000 bản ghi được thực thi nạp trong một giao dịch độc lập. Nếu xảy ra lỗi gián đoạn, hệ thống tự động rollback mà không làm suy chuyển tính toàn vẹn của dữ liệu đã nạp.
- **Bộ nạp hàng loạt (Bulk Appender)**: Tận dụng cơ chế ghi trực tiếp theo khối của DuckDB, đạt tốc độ nạp trung bình trên $35,000$ records/giây, rút ngắn tổng thời gian chuyển đổi toàn bộ 2.68 triệu issues xuống dưới 45 phút trên phần cứng thông thường.

---

## 2.4. KHÁM PHÁ DỮ LIỆU (EXPLORATORY DATA ANALYSIS - EDA)

Mục tiêu cốt lõi của quá trình khám phá dữ liệu là thấu hiểu các đặc tính thống kê cơ bản, phát hiện các hiện tượng dị thường (data anomalies) và rò rỉ nhãn (data leakage), từ đó tạo lập cơ sở khoa học để thiết kế các đặc trưng học máy vững chắc.

![Hình 2.2: Phân tích Thống kê Toàn diện Khám phá Dữ liệu (EDA Compendium)](figures/eda_multi_analysis.png)

---

### 2.4.1. Phân tích Dữ liệu Thiếu (Missing Data Analysis)

Dữ liệu khai thác từ các hệ thống quản lý công việc phần mềm thực tế thường phản ánh tính tự nhiên trong thói quen của con người, dẫn đến tình trạng khuyết thiếu dữ liệu mang tính quy luật (**Missing Not at Random - MNAR**).

#### Bảng 2.1: Tỷ lệ khuyết thiếu dữ liệu của các thuộc tính chính
| Thuộc tính | Kiểu dữ liệu | Tỷ lệ khuyết (JFrog) | Tỷ lệ khuyết (Spring) | Cơ chế và Ý nghĩa nghiệp vụ |
| :--- | :---: | :---: | :---: | :--- |
| `assignee` | Định danh | **39.1%** | **10.2%** | Issue được đưa lên backlog nhưng chưa phân công cho kỹ sư cụ thể (`is_unassigned = 1`). |
| `resolution` | Phân loại | **34.2%** | **11.0%** | Chỉ được thiết lập khi nhiệm vụ hoàn tất. Khuyết khi nhiệm vụ còn mở (`is_resolved = 0`). |
| `story_points` | Số nguyên | **82.4%** | **84.6%** | Đa số các dự án mã nguồn mở không áp dụng chấm điểm Story Points một cách bắt buộc. |
| `priority` | Phân loại | **0.7%** | **0.9%** | Rất ít khi khuyết; khi khuyết được quy về mức mặc định *Normal / Minor*. |
| `comments` | Danh sách | **48.3%** | **18.7%** | Tác vụ đơn giản được xử lý nhanh thường không phát sinh thảo luận kỹ thuật. |

#### Hệ quả mô hình hóa:
1. **Thuộc tính `assignee`**: Tình trạng chưa gán người nhận việc (`is_unassigned = 1`) không phải là lỗi dữ liệu cần loại bỏ (drop), mà ngược lại, là một đặc trưng dự báo có giá trị SHAP rất cao (xếp thứ 2 trong mô hình XGBoost), phản ánh nguy cơ nhiệm vụ bị bỏ quên trên hệ thống.
2. **Thuộc tính `story_points`**: Do tỷ lệ khuyết thiếu vượt quá 80%, các mô hình học máy không thể dựa trực tiếp vào trường dữ liệu này. Nghiên cứu đã thiết kế chỉ số **Proxy Story Points** kết hợp giữa độ dài mô tả yêu cầu (NLP), mức độ ưu tiên và thể loại công việc:
   $$\text{SP}_{\text{proxy}} = \text{round}\left(1.0 + 3.0 \cdot \text{priority\_norm} + \text{theme\_weight} + 2.0 \cdot \min\left(\frac{\text{word\_count}}{15}, 1.0\right)\right)$$

---

### 2.4.2. Phân tích Thuộc tính Tác vụ (Issue Type, Priority, Status, Resolution)

#### 1. Thể loại công việc (Issue Type & Themes)
Các loại nhiệm vụ được gom nhóm theo 4 chủ đề kỹ thuật chuẩn hóa (Hình 2.2a):
- **Bảo trì hệ thống (Maintenance - Bug/Defect)**: Chiếm $39\%$ ở Spring và $53\%$ ở JFrog. Nhóm tác vụ này có độ biến thiên thời gian giải quyết rất cao do tính chất khó lường của lỗi phần mềm.
- **Phát triển tính năng (Requirements - New Feature/Improvement/Epic)**: Chiếm $44\%$ ở Spring và $32\%$ ở JFrog. Thường có kế hoạch dài hạn và liên quan đến nhiều phụ thuộc.
- **Công việc kỹ thuật nội bộ (Development - Task/Subtask/Refactoring)**: Chiếm $8\% - 16\%$.
- **Hỗ trợ người dùng & Khác (User Support / RCA)**: Chiếm $1\% - 7\%$.

#### 2. Mức độ ưu tiên (Priority)
Phân phối mức độ ưu tiên thể hiện tính bất cân xứng rõ rệt:
- Mức trung bình (*Normal* / *Major* / *Minor*) chiếm đa số áp đảo: **$72\%$** ở JFrog và **$57\%$** ở Spring.
- Mức khẩn cấp (*Critical* / *Blocker*) chỉ chiếm từ **$3\%$ đến $10\%$**.
- Điều này đòi hỏi quy trình mã hóa đặc trưng phải sử dụng kỹ thuật *Target Encoding* có làm mịn (Smoothed Target Encoding) theo công thức $m$-estimate để tránh hiện tượng quá khớp (overfitting) trên các nhóm ưu tiên hiếm.

#### 3. Quy trình Trạng thái (Status Flow)
Khi khảo sát $31.78$ triệu sự kiện biến động trạng thái, nghiên cứu phát hiện hiện tượng **Đóng việc tắt (Direct Close)**:
- Tại hệ sinh thái Spring, có tới **$43,553$ lượt** chuyển dịch trực tiếp từ trạng thái mới tạo (*New / Open*) sang kết thúc (*Done / Closed*), vượt xa số lượt chuyển dịch qua trạng thái trung gian "Đang làm" (*In Progress* - $17,466$ lượt).
- *Nguyên nhân nghiệp vụ*: Các lập trình viên thường giải quyết công việc trên nhánh mã nguồn cá nhân (local git branch) và chỉ cập nhật Jira một lần duy nhất khi tạo Merge/Pull Request. 

#### 4. Kết quả xử lý cuối cùng (Resolution)
Cơ cấu kết quả xử lý (Hình 2.2d) bộc lộ sự hiện diện của hai nhóm nhiệm vụ đặc biệt:
- **Nhiệm vụ hoãn có chủ đích**: $16\%$ issue JFrog đóng với nhãn `Deferred` và $9\%$ issue Spring đóng với nhãn `Won't Fix`. Các nhiệm vụ này có thời gian mở rất dài nhưng không phải do trễ hạn kỹ thuật mà do quyết định điều chỉnh lộ trình sản phẩm của ban quản trị.
- **Nhiệm vụ ảo (Non-Work Tasks)**: Lỗi trùng lặp (`Duplicate` - $22.98\%$ ở tập Test), lỗi không tái hiện được (`Cannot Reproduce` / `Not a Bug` - $12.76\%$). Nhóm này cần một cổng phân loại sơ tuyển (Pre-triage Gate) độc lập để làm sạch trước khi đưa vào mô hình dự đoán trễ hạn.

---

### 2.4.3. Phân tích Yếu tố Thời gian (Temporal Dynamics Analysis)

Dữ liệu chuỗi thời gian trong quản lý dự án phần mềm có những đặc thù phân phối mang tính phi chuẩn:

#### 1. Phân phối Vòng đời Nhiệm vụ (Cycle Time / Resolution Duration)
Phân phối thời gian từ lúc tạo đến lúc đóng nhiệm vụ có dạng lệch phải cực hạn (Heavy-tailed distribution, tiệm cận log-normal) như minh họa tại Hình 2.2b:
- **Tại JFrog**: Trung vị ($p50$) là **$46$ ngày**, nhưng bách phân vị $p90$ lên tới **$2,207$ ngày** (~6 năm) và $p99$ lên tới **$3,915$ ngày** (>10 năm).
- **Tại Spring**: Trung vị ($p50$) là **$11$ ngày**, nhưng $p90$ là **$659$ ngày** và $p99$ đạt **$2,825$ ngày**.

#### Bảng 2.2: Thời gian lưu trú (Dwell Time) theo từng trạng thái công việc (đơn vị: Ngày)
| Instance | Trạng thái công việc | Số đoạn ghi nhận | Trung vị ($p50$) | Bách phân vị $p90$ | Cực trị ($p99$) |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **JFrog** | *In Progress* (Đang làm) | 3,209 | **0.9** | 17.9 | 142.8 |
| | *Pending QA* (Chờ kiểm thử) | 5,901 | **2.1** | 21.8 | 85.9 |
| | *Open* (Tồn đọng Backlog) | 11,148 | **22.8** | 2,152.0 | 3,857.0 |
| **Spring** | *In Progress* (Đang làm) | 19,932 | **0.15** | 11.9 | 205.0 |
| | *Waiting for Feedback* (Chờ phản hồi) | 2,329 | **4.4** | 476.0 | 2,407.0 |
| | *Open* (Tồn đọng Backlog) | 59,206 | **5.9** | 510.0 | 2,735.0 |

#### 2. Tính chất Lưỡng cực của Khoảng cách Sự kiện (Inter-Event Interval)
Khoảng thời gian giữa hai sự kiện liên tiếp của cùng một issue biểu hiện tính lưỡng cực sâu sắc:
- Khi issue đang được giải quyết tích cực, các sự kiện chuyển trạng thái và bình luận diễn ra liên tục cách nhau vài phút đến vài giờ ($p50 = 0.29$ ngày tại Spring).
- Ngược lại, $10\%$ khoảng cách sự kiện dài hơn $3 - 4$ năm. Đối với các issue đang mở, thời gian không hoạt động trung vị lên tới **$622$ ngày** (JFrog) và **$2,396$ ngày** (Spring), thực chất là các nhiệm vụ "chết" bị lãng quên trong kho lưu trữ.

---

### 2.4.4. Phân tích Hành vi Quy trình (Process Behavior Analysis)

Khai phá quy trình thông qua nhật ký biến động (`issue_changelogs`) làm sáng tỏ các mẫu hành vi tác động trực tiếp đến rủi ro trễ tiến độ:

#### 1. Hành vi Mở lại Tác vụ (Reopen Rate)
- Tỷ lệ nhiệm vụ bị mở lại sau khi đã đóng (*Reopened*) chiếm **$3.92\%$** ở JFrog ($1,325$ đoạn) và **$4.45\%$** ở Spring ($3,252$ đoạn).
- Phân tích thống kê cho thấy các nhiệm vụ có lịch sử reopen có xác suất trễ hạn cao gấp **$2.42$ lần** so với nhiệm vụ được giải quyết dứt điểm trong một chu kỳ duy nhất.

#### 2. Hiện tượng Đổi người Phụ trách Nhiều lần (Ping-Pong Assignment)
- Có **$1.49\%$** issue JFrog và **$0.63\%$** issue Spring bị thay đổi người phụ trách $\ge 3$ lần.
- Đây là dấu hiệu điển hình của việc yêu cầu kỹ thuật không rõ ràng hoặc chuyển giao trách nhiệm lòng vòng, làm gia tăng thời gian chờ trung bình thêm **$318\%$**.

#### 3. Dị thường Đóng hàng loạt (Bulk Close Anomalies)
EDA phát hiện hiện tượng quản trị bất thường:
- **JFrog**: Ghi nhận **91 đợt** đóng hàng loạt, với tổng cộng **$8,044$ issues ($52\%$ toàn bộ hệ sinh thái)** bị đóng bởi cùng một kỹ sư trong cùng một phút.
- **Spring**: Ghi nhận **354 đợt** đóng hàng loạt, ảnh hưởng tới **$26,008$ issues ($38\%$)**.
- *Tác động*: Thời gian tồn tại của các issue này trước khi đóng thực chất là thời gian "nằm chờ dọn dẹp hệ sinh thái", không phản ánh thời gian lao động kỹ thuật thực sự. Mô hình cần thiết lập bộ lọc phát hiện đợt đóng hàng loạt nhằm tránh làm sai lệch hàm phân phối thời gian xử lý.

---

### 2.4.5. Phân tích Mạng Phụ thuộc và Nguồn lực (Dependency & Resource Network Analysis)

#### 1. Cấu trúc Mạng Lưới Phụ thuộc Công việc (Issue Dependency DAG)
- Có khoảng **$20.5\% - 21.0\%$** các nhiệm vụ sở hữu ít nhất một liên kết với nhiệm vụ khác.
- Tuy nhiên, các liên kết phụ thuộc có hướng mang tính cản trở trực tiếp (*Blocks* hoặc *Depends on*) chỉ chiếm **$3.01\%$** (JFrog) và **$4.04\%$** (Spring).
- Tỷ lệ các nhiệm vụ có quan hệ phụ thuộc mà nhiệm vụ đối ứng **vẫn đang mở** chỉ chiếm **$0.12\%$** (JFrog) và **$0.29\%$** (Spring).
- *Ý nghĩa kiến trúc*: Phần lớn các liên kết là quan hệ tham chiếu mềm (`Relates to`), còn đồ thị phụ thuộc găng (`Blocks/Depends`) rất thưa. Trong mô hình đồ thị động (Continuous-Time Dynamic Graph), có tới **$96.4\% - 97.1\%$ các sự kiện là khuyên tự trỏ (Self-loops)** từ issue về chính nó. Do đó, cơ chế Temporal Graph Attention chủ yếu đóng vai trò học lại lịch sử của chính nút, bổ sung khả năng lan truyền tín hiệu khi xuất hiện liên kết thực sự.

#### 2. Mạng Lưới Phân công Nguồn lực (Resource Allocation Inequality)
Phân tích mức độ tập trung khối lượng công việc giữa các kỹ sư phát triển thông qua **Đường cong Lorenz** (Hình 2.2c):
- Hệ số bất bình đẳng Gini về tải công việc đạt mức rất cao: **$G = 0.838$** (JFrog) và **$G = 0.820$** (Spring).
- Nhóm **$10$ kỹ sư chủ chốt** (chiếm chưa đầy $5\%$ nhân sự) gánh vác tới **$60.6\%$** tổng số nhiệm vụ tại JFrog và **$46.2\%$** tại Spring.
- Khi các nhân sự hạt nhân này tiếp nhận thêm nhiệm vụ mới trong bối cảnh hàng đợi đang tắc nghẽn, nguy cơ trễ hạn của các nhiệm vụ mới tăng vọt theo hàm số mũ.

---

### 2.4.6. Phân tích Nhãn Rủi ro và Tương quan Đặc trưng (Risk Labels & Feature Correlation)

#### 1. Mối tương quan giữa các Nhóm Đặc trưng và Biến Mục tiêu
Phân tích hệ số tương quan tuyến tính Pearson và tương quan phi tuyến Spearman giữa ma trận đặc trưng trích xuất tại mốc $T_0$ (`created_ts`) và biến mục tiêu `is_delayed = 1` mang lại các hiểu biết định lượng quan trọng:

#### Bảng 2.3: Top các đặc trưng có lực phân tách rủi ro trễ hạn mạnh nhất
| Tên đặc trưng | Nhóm bản chất | Hệ số tương quan ($r$) | Tác động định tính theo SHAP Value |
| :--- | :--- | :---: | :--- |
| `active_per_completed` | Tải nguồn lực | **+0.4617** | Tỷ số giữa số task đang mở và số task đã hoàn thành trong quá khứ của assignee. Khi tỷ số này tăng cao, kỹ sư rơi vào tình trạng quá tải nghiêm trọng. |
| `is_unassigned` | Phân công | **+0.3136** | Thẻ nhiệm vụ chưa có người tiếp nhận tại thời điểm tạo, dẫn đến thời gian chờ ban đầu bị kéo dài vô thời hạn. |
| `project_active_count` | Tải dự án | **+0.1281** | Tổng số nhiệm vụ đang đồng thời kích hoạt trong toàn bộ dự án, phản ánh độ nghẽn chung của tổ chức. |
| `assignee_hist_completed` | Năng lực lịch sử | **-0.0946** | Số lượng nhiệm vụ kỹ sư đã xử lý thành công trong quá khứ; giá trị càng cao biểu thị thâm niên và năng suất, giảm rủi ro trễ. |
| `mean_hist_delay` | Xác suất tiên nghiệm | **+0.0777** | Tỷ lệ trễ hạn trung bình lịch sử kết hợp giữa kỹ sư phụ trách (`assignee`) và người tạo thẻ (`reporter`). |
| `ambiguity_index` | Ngữ nghĩa NLP | **+0.0412** | Tỷ lệ từ ngữ thể hiện sự mơ hồ trong phần tóm tắt yêu cầu kỹ thuật (*"maybe", "should", "investigate", "tbd"*). |

#### 2. Bài học Thực nghiệm về Rò rỉ Nhãn (Label Leakage & Feature Hygiene)
Một phát hiện mang tính bước ngoặt trong giai đoạn thử nghiệm sơ khởi của đề tài là nguy cơ rò rỉ dữ liệu qua đặc trưng liên kết:
- Trong thiết lập thử nghiệm ban đầu (nhãn $v3$: *"Issue có liên kết Block/Depend"*), mô hình TGN đạt diện tích dưới đường cong ROC-AUC rất cao là **$0.835$** trên tập kiểm thử JFrog.
- Tuy nhiên, quá trình kiểm toán đặc trưng (Feature Attribution Audit) phát hiện ra rằng: đặc trưng one-hot phân loại liên kết cạnh đồ thị đã vô tình làm lộ thông tin nhãn, bởi vì $100\%$ ($432/432$) các issue mang nhãn dương đều phát sinh sự kiện liên kết trước khi có nhãn.
- Khi loại bỏ đặc trưng rò rỉ này, ROC-AUC thực tế của mô hình giảm ngay từ **$0.835$ xuống $0.620$**, và khi loại bỏ hoàn toàn các sự kiện liên kết, AUC rơi về mức **$0.484$** (tương đương đoán ngẫu nhiên).

*Kết luận rút ra*: Đề tài tuyệt đối không sử dụng bất kỳ thông tin nào xuất hiện sau thời điểm tạo issue ($t > \text{created\_ts}$) trong các bài toán dự đoán tại $T_0$. Toàn bộ 264 chiều đặc trưng số đều được trích xuất thông qua thuật toán mô phỏng sự kiện lịch sử $O(N)$ nghiêm ngặt, đảm bảo tính khách quan và khả năng ứng dụng thực tế của mô hình trong môi trường công nghiệp.


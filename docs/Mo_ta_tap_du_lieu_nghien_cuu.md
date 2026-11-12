# CHƯƠNG 3: PHƯƠNG PHÁP NGHIÊN CỨU VÀ DỮ LIỆU THỰC NGHIỆM

## 3.1. MÔ TẢ TẬP DỮ LIỆU NGHIÊN CỨU

### 3.1.1. Nguồn gốc và xuất xứ tập dữ liệu (Data Provenance)

Để giải quyết bài toán dự đoán rủi ro trễ hạn nhiệm vụ phần mềm và phân tích độ trọng yếu của công việc trong các dự án thực tế, nghiên cứu này sử dụng kho dữ liệu **The Public Jira Dataset** được công bố bởi nhóm tác giả Montgomery, Lüders và Maalej tại Hội nghị Quốc tế về Khai phá Kho Phần mềm (*IEEE/ACM International Conference on Mining Software Repositories - MSR 2022*). Tập dữ liệu được lưu trữ và chia sẻ chính thức trên kho lưu trữ khoa học Zenodo theo giấy phép bản quyền mở Creative Commons Attribution 4.0 International (CC-BY-4.0).

Kho dữ liệu này ghi nhận quá trình vận hành, phát triển và tương tác phần mềm xuyên suốt hơn hai thập kỷ (giai đoạn từ 2001 đến 2022) từ **16 hệ sinh thái phần mềm lớn trên thế giới**, bao gồm cả các tổ chức mã nguồn mở quy mô cộng đồng lẫn các dự án phần mềm thương mại công nghiệp:
- **Tập đoàn & Dự án quốc tế**: *Apache Software Foundation, Atlassian Jira, Mojang (Minecraft), Spring Framework, RedHat, MongoDB, Qt Project, JFrog, MariaDB, Sonatype, Hyperledger, Sakai, IntelDAOS, JiraEcosystem, Mindville, SecondLife*.
- **Tính pháp lý và ẩn danh (Anonymization)**: Nhằm tuân thủ các quy chuẩn đạo đức nghiên cứu và bảo vệ quyền riêng tư, toàn bộ định danh cá nhân (như tài khoản người tạo `reporter`, người thực hiện `assignee`, người bình luận `author`) đã được làm mờ thông qua việc mã hóa sang chuỗi UUID4 ẩn danh dạng chuẩn (`<<|author_name|<uuid>|>>`), đảm bảo phân biệt được hành vi độc lập của từng kỹ sư nhưng không làm lộ danh tính thực tế.

---

### 3.1.2. Quy mô và cấu trúc mô hình dữ liệu (Data Topology & Schema)

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

### 3.1.3. Mô tả các thuộc tính đặc trưng cốt lõi (Data Attributes)

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

### 3.1.4. Định nghĩa biến mục tiêu (Target Variable Definition)

Trong nghiên cứu này, bài toán trọng tâm là dự đoán sớm nguy cơ chậm trễ tiến độ của một nhiệm vụ phần mềm. Biến mục tiêu $y \in \{0, 1\}$ (`is_delayed`) là một biến nhị phân được xác định toán học như sau:

$$y_i = \begin{cases} 
1 & \text{nếu } t_{\text{actual\_duration}}^{(i)} > t_{\text{planned\_duration}}^{(i)} \quad \text{(Bị trễ hạn)} \\ 
0 & \text{ngược lại} \quad \text{(Hoàn thành đúng hạn hoặc sớm hạn)} 
\end{cases}$$

Trong đó:
- $t_{\text{actual\_duration}}^{(i)} = t_{\text{resolved\_ts}}^{(i)} - t_{\text{created\_ts}}^{(i)}$ là tổng thời lượng thực tế từ lúc khởi tạo đến lúc hoàn tất nhiệm vụ.
- $t_{\text{planned\_duration}}^{(i)}$ là thời gian kỳ vọng được xác định từ mốc hạn chót (`due_date`) hoặc ước tính theo năng lực lịch sử của đội ngũ phát triển tại thời điểm giao việc.

---

### 3.1.5. Thống kê mô tả và các thách thức đặc thù của dữ liệu (Data Characteristics & Challenges)

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

### 3.1.6. Chiến lược phân chia dữ liệu thực nghiệm (Strict Chronological Split)

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

### 3.1.7. Tóm tắt tiểu mục

Tập dữ liệu The Public Jira Dataset với hơn 2.68 triệu tác vụ và hàng chục triệu bản ghi tương tác là nguồn tri thức phong phú, phản ánh chân thực các quy luật vận hành và rủi ro chậm trễ trong các dự án phần mềm hiện đại. Việc phân chia dữ liệu bất biến theo thời gian (Strict Chronological Split) và nhận diện sớm các thách thức về dịch chuyển phân phối, dữ liệu kiểm duyệt và tác vụ ảo là tiền đề then chốt để xây dựng quy trình tiền xử lý và kỹ nghệ đặc trưng (Feature Engineering) khoa học ở các phần tiếp theo của báo cáo.

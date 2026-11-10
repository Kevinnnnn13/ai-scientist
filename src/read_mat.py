"""第4个程序：用 scipy 读取第一块电池的体检报告 B0005.mat"""
from scipy.io import loadmat

mat = loadmat(r"C:\Users\22011\Desktop\26暑假\ai_scientist\data\Battery_DataSet\Battery_DataSet\B0005.mat")
print("=== 顶层字典的 key ===")
print(list(mat.keys()))          # 看到 '__header__', 'B0005' 等

battery = mat["B0005"]
print("B0005 形状:", battery.shape)

cell = battery[0, 0]
print("结构体字段:", cell.dtype.names)      # 应该看到 ('cycle',)

cycles = cell["cycle"]
print("循环总数:", cycles.shape)            # 应该是 (1, 616)

c0 = cycles[0, 0]
print("单个循环的字段:", c0.dtype.names)    # ('type', 'ambient_temperature', 'time', 'data')
print("第一个循环的类型:", c0["type"][0])    # charge / discharge / impedance
print("data 里的测量字段:", c0["data"].dtype.names)



# from scipy.io import loadmat
# mat = loadmat(r"C:\Users\22011\Desktop\26暑假\ai_scientist\data\Battery_DataSet\Battery_DataSet\B0005.mat")
# print("=== 顶层字典的 key ===")
# print(list(mat.keys()))      #第一步，先找到标题中对应的有意义的一项

# print(type(mat['B0005']))    #第二步，看看这个有意义的项是什么数据类型
# print(mat['B0005'].shape)    #      并且看看这个东西有多大

# cell=mat['B0005'][0, 0]      #第三步，把这个有意义的项取出来
# print(type(cell))                #      看看这个东西是什么数据类型

# print(cell.dtype.names)      #       看看这里面有什么东西

# cycles = cell["cycle"]       #第四步，把这个有意义的项取出来
# print("循环总数:", cycles.shape)#     看看形状是什么

# first_cycle = cycles[0, 0]   #第五步，取出第一步循环，看看内容
# print("单次循环的格子：", first_cycle.dtype.names)

# data = first_cycle["data"]    #第六步，去处其中最重要的数据，data，看看里面有什么
# print("测量数据字段：", data.dtype.names)